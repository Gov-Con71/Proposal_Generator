"""Company-profile persistence (Sprint 5).

One `company_profiles` row per tenant (keyed by user_id, matching the
history_service tenancy model). List/object fields live in JSONB columns.
Reads never mutate: a tenant with no row yet gets an empty default object.
Saves upsert the merged profile.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from app.core.db import get_connection
from app.models.contract import CompanyProfile, CompanyProfileUpdate, PastPerformance

logger = logging.getLogger(__name__)

# Columns in table order — the single source of truth for read/write SQL.
_COLS = (
    "legal_name", "duns_number", "uei_number", "primary_address", "cage_code",
    "naics_code", "naics_description", "cmmc_level", "socio_economic_status",
    "annual_revenue", "fringe_rate", "overhead_rate", "ga_rate",
    "capabilities_overview", "certifications", "security_clearance",
    "past_performance", "updated_at",
)
_JSON_COLS = {"socio_economic_status", "certifications", "past_performance"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_profile(user_id: UUID) -> CompanyProfile:
    return CompanyProfile(id=str(user_id), updated_at=_now())


def _to_profile(row: dict) -> CompanyProfile:
    """Maps a DB row (JSONB already decoded by psycopg2) to the contract model."""
    return CompanyProfile(
        id=str(row["user_id"]),
        legal_name=row["legal_name"],
        duns_number=row["duns_number"],
        uei_number=row["uei_number"],
        primary_address=row["primary_address"],
        cage_code=row["cage_code"],
        naics_code=row["naics_code"],
        naics_description=row["naics_description"],
        cmmc_level=row["cmmc_level"],
        socio_economic_status=row["socio_economic_status"] or [],
        annual_revenue=float(row["annual_revenue"]),
        fringe_rate=float(row["fringe_rate"]),
        overhead_rate=float(row["overhead_rate"]),
        ga_rate=float(row["ga_rate"]),
        capabilities_overview=row["capabilities_overview"],
        certifications=row["certifications"] or [],
        security_clearance=row["security_clearance"],
        past_performance=[PastPerformance(**pp) for pp in (row["past_performance"] or [])],
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
    )


def get_profile(user_id: UUID) -> CompanyProfile:
    """Returns the tenant's stored profile, or an empty default if none exists."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, " + ", ".join(_COLS) + " FROM company_profiles WHERE user_id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _to_profile(row) if row else _default_profile(user_id)


def save_profile(user_id: UUID, patch: CompanyProfileUpdate) -> CompanyProfile:
    """Merges a partial update onto the current profile and upserts it."""
    current = get_profile(user_id)
    merged_data = current.model_dump()
    merged_data.update(patch.model_dump(exclude_none=True))
    merged_data["updated_at"] = _now()
    # Re-validate so nested past_performance dicts become PastPerformance models.
    merged = CompanyProfile.model_validate(merged_data)

    values = {
        "legal_name": merged.legal_name,
        "duns_number": merged.duns_number,
        "uei_number": merged.uei_number,
        "primary_address": merged.primary_address,
        "cage_code": merged.cage_code,
        "naics_code": merged.naics_code,
        "naics_description": merged.naics_description,
        "cmmc_level": merged.cmmc_level,
        "socio_economic_status": Json(merged.socio_economic_status),
        "annual_revenue": merged.annual_revenue,
        "fringe_rate": merged.fringe_rate,
        "overhead_rate": merged.overhead_rate,
        "ga_rate": merged.ga_rate,
        "capabilities_overview": merged.capabilities_overview,
        "certifications": Json(merged.certifications),
        "security_clearance": merged.security_clearance,
        "past_performance": Json([pp.model_dump() for pp in merged.past_performance]),
        "updated_at": merged.updated_at,
    }
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS)
    placeholders = ", ".join(["%s"] * (len(_COLS) + 1))  # +1 for user_id

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO company_profiles (user_id, {', '.join(_COLS)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {assignments};",
                (str(user_id), *[values[c] for c in _COLS]),
            )
    finally:
        conn.close()
    logger.info("save_profile: upserted profile for tenant %s", user_id)
    return merged
