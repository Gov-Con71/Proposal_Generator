"""Contract drift guard (Sprint 8).

The backend's Pydantic models and the frontend's TypeScript types describe the
same JSON. Nothing enforced that, and they drifted: `contract.UploadResponse`
advertised `documentId`/`proposalId` while the real upload endpoint returned
`rfpId`. This test fails CI when the two sides disagree.

It compares field *names* (camelCase on the wire), not types — that is what
catches renames, additions, and removals, which is the drift that actually
breaks the client.
"""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.openapi.utils import get_openapi

from app.main import app

# The frontend lives outside the backend container's /code mount, so this test
# only runs where the whole repo is checked out (CI, and local dev).
TYPES_FILE = Path(__file__).resolve().parents[2] / "proposalai-frontend" / "types" / "index.ts"

# TS interface -> OpenAPI component schema. Only response/request shapes the
# frontend actually exchanges with the API belong here.
CHECKED: dict[str, str] = {
    "User": "User",
    "Session": "Session",
    "PastPerformance": "PastPerformance",
    "CompanyProfile": "CompanyProfile",
    "Requirement": "Requirement",
    "ProposalSection": "ProposalSection",
    "ProposalSummary": "ProposalSummary",
    # Added after `draftingStatus`/`draftingFailureReason` landed on both sides
    # (migration 0005). The full Proposal was unchecked while its summary was,
    # so precisely the fields this change touched were the ones nothing guarded.
    "Proposal": "Proposal",
    "IntegrityItem": "IntegrityItem",
    "ExportJob": "ExportJob",
}

# Captures the name, any `extends A, B` clause, and the body. The extends group
# is why this is not a simpler pattern: without it, `export interface Proposal
# extends ProposalSummary {` did not match *at all*, so the interface was
# invisible to the guard rather than mismatched by it — a check that silently
# covers nothing, which is the failure mode this whole file exists to prevent.
_INTERFACE_RE = re.compile(
    r"export\s+interface\s+(\w+)\s*(?:extends\s+([\w\s,]+?))?\s*\{(.*?)\n\}", re.DOTALL
)
# A property line: `  name?: type`. Excludes methods and index signatures.
_FIELD_RE = re.compile(r"^\s*(\w+)\s*\??\s*:", re.MULTILINE)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", src)


def _collapse_nested(body: str) -> str:
    """Removes the contents of nested object literals, keeping the field itself.

    `administrative: { solicitation_number: Citation }` collapses to
    `administrative: `, so the flat field regex sees one field named
    `administrative` and none of the inner names.

    The parser used to assert the contract file stayed flat. `SolicitationSummary`
    then landed with nested literals, and because the assert runs in a fixture it
    turned every parameterised case into a collection *error* — so the guard
    stopped comparing anything at all, in exactly the silent way it exists to
    prevent.
    """
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _ts_interfaces(src: str) -> dict[str, set[str]]:
    """Maps each exported TS interface to its field names, inherited ones included.

    Inheritance has to be resolved because the comparison is against OpenAPI,
    which flattens it: Pydantic's `Proposal(ProposalSummary)` publishes one
    schema carrying every field, so a TS `Proposal extends ProposalSummary` only
    matches once its parent's fields are merged in.
    """
    own: dict[str, set[str]] = {}
    parents: dict[str, list[str]] = {}
    for name, extends, body in _INTERFACE_RE.findall(_strip_comments(src)):
        own[name] = set(_FIELD_RE.findall(_collapse_nested(body)))
        parents[name] = [p.strip() for p in extends.split(",") if p.strip()]

    def resolve(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        # `seen` guards against a cycle in the declarations rather than trusting
        # the source to be well-formed; a RecursionError here would surface as
        # an unrelated-looking collection error.
        if name in seen or name not in own:
            return set()
        fields = set(own[name])
        for parent in parents.get(name, []):
            fields |= resolve(parent, seen | {name})
        return fields

    return {name: resolve(name) for name in own}


@pytest.fixture(scope="module")
def openapi_schemas() -> dict[str, dict]:
    spec = get_openapi(title=app.title, version="1.0.0", routes=app.routes)
    return spec["components"]["schemas"]


@pytest.fixture(scope="module")
def ts_interfaces() -> dict[str, set[str]]:
    if not TYPES_FILE.exists():
        # CI sets CONTRACT_STRICT because it has the whole repo checked out;
        # a skip there would mean the guard quietly checks nothing.
        if os.getenv("CONTRACT_STRICT"):
            pytest.fail(f"CONTRACT_STRICT is set but frontend types are missing: {TYPES_FILE}")
        pytest.skip(f"frontend types not available at {TYPES_FILE}")
    return _ts_interfaces(TYPES_FILE.read_text())


def test_parser_finds_the_interfaces_it_checks(ts_interfaces):
    """Guards the regex itself: a silently-empty parse would make every
    comparison below pass vacuously."""
    missing = sorted(set(CHECKED) - set(ts_interfaces))
    assert not missing, f"TS interfaces not found (parser broken or renamed): {missing}"


@pytest.mark.parametrize("ts_name,schema_name", sorted(CHECKED.items()))
def test_ts_type_matches_openapi_schema(ts_name, schema_name, ts_interfaces, openapi_schemas):
    assert schema_name in openapi_schemas, f"{schema_name} missing from OpenAPI"

    api_fields = set(openapi_schemas[schema_name].get("properties", {}))
    ts_fields = ts_interfaces[ts_name]

    only_api = sorted(api_fields - ts_fields)
    only_ts = sorted(ts_fields - api_fields)

    assert not only_api and not only_ts, (
        f"{ts_name} (TS) and {schema_name} (API) disagree.\n"
        f"  only in API: {only_api}\n"
        f"  only in TS : {only_ts}"
    )


def test_no_orphaned_response_models(openapi_schemas):
    """Every component schema should be reachable from a route. An unreferenced
    one is dead weight that drifts unnoticed — exactly how UploadResponse
    described a payload no endpoint ever returned."""
    spec = json.dumps(get_openapi(title=app.title, version="1.0.0", routes=app.routes)["paths"])
    referenced = set(re.findall(r"#/components/schemas/(\w+)", spec))

    # Schemas reached only via another schema's $ref (nested models).
    for name, schema in openapi_schemas.items():
        for nested in re.findall(r"#/components/schemas/(\w+)", json.dumps(schema)):
            if name in referenced:
                referenced.add(nested)

    orphans = sorted(set(openapi_schemas) - referenced)
    assert not orphans, f"OpenAPI schemas not used by any route: {orphans}"
