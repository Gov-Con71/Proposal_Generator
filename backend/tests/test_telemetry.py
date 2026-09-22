"""Story 5.3 — LLM telemetry unit test (fake Redis, no network)."""

import types

import pytest

from app.core import telemetry


class _FakePipe:
    def __init__(self, store):
        self.store, self.ops = store, []

    def hincrby(self, h, k, v):
        self.ops.append((h, k, v)); return self

    def hincrbyfloat(self, h, k, v):
        self.ops.append((h, k, v)); return self

    def execute(self):
        for h, k, v in self.ops:
            self.store.setdefault(h, {})
            self.store[h][k] = self.store[h].get(k, 0) + v
        self.ops = []


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return _FakePipe(self.store)

    def hgetall(self, h):
        return {str(k).encode(): str(v).encode() for k, v in self.store.get(h, {}).items()}


@pytest.fixture
def fake_redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(telemetry, "_redis", lambda: r)
    monkeypatch.setattr(telemetry.settings, "telemetry_enabled", True)
    return r


def _response(prompt, candidates):
    return types.SimpleNamespace(
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=candidates
        )
    )


def test_records_tokens_and_estimates_cost(fake_redis):
    start = telemetry.now()
    telemetry.record_response("gemini-2.0-flash", _response(1_000_000, 500_000), start)
    telemetry.record_error("gemini-2.0-flash", start)

    snap = telemetry.metrics_snapshot()
    assert snap["available"] is True
    model = snap["by_model"]["gemini-2.0-flash"]
    assert model["calls"] == 2  # one success + one error both count as calls
    assert model["errors"] == 1
    assert model["tokens_in"] == 1_000_000
    assert model["tokens_out"] == 500_000
    # 1M in @ $0.10 + 0.5M out @ $0.40 = 0.10 + 0.20 = $0.30
    assert model["est_cost_usd"] == pytest.approx(0.30, abs=1e-6)
    assert snap["totals"]["cost_usd"] == pytest.approx(0.30, abs=1e-6)


def test_missing_usage_metadata_is_safe(fake_redis):
    telemetry.record_response("gemini-2.0-flash", types.SimpleNamespace(), telemetry.now())
    snap = telemetry.metrics_snapshot()
    assert snap["by_model"]["gemini-2.0-flash"]["tokens_in"] == 0


def test_priced_flag_distinguishes_a_real_zero_from_an_unpriced_model(fake_redis):
    """A Featherless model (genuinely flat-rate, $0 marginal cost) and a model
    with no _PRICES entry at all both report est_cost_usd == 0.0 — priced must
    be the only thing telling those two cases apart."""
    telemetry.record_response("Qwen/Qwen2.5-7B-Instruct", _response(1000, 500), telemetry.now())
    telemetry.record_response("some-new-unpriced-model", _response(1000, 500), telemetry.now())

    snap = telemetry.metrics_snapshot()
    known_zero = snap["by_model"]["Qwen/Qwen2.5-7B-Instruct"]
    unknown = snap["by_model"]["some-new-unpriced-model"]

    assert known_zero["est_cost_usd"] == 0.0
    assert known_zero["priced"] is True

    assert unknown["est_cost_usd"] == 0.0
    assert unknown["priced"] is False
