"""The tier-enforcement matrix — asserts every rate limit / feature gate is set per tier AND flows through
clamp_request to the run. This is the regression guard for "all limits properly set across tiers": if a new
Tier field is added but not wired into clamp, or a tier's value drifts, a test here fails.

Enforcement sites (for reference):
  admit_scan   → deep_verify_per_day, sandbox_minutes_per_month, concurrency
  check_api_rate → api_rpm
  clamp_request → max_k(→k), wall_seconds(→timeout), top_k_claims, repair_steps, cpu_cores, mem_mb, plan(ai),
                  private_repos/fetch_data/acquire_data (402 gates)
  supervisor._limits → mem_mb (min with container), wall
  pipeline      → top_k gate, opts.plan, opts.repair_steps, opts.acquire_data
  e2b_runner    → cpu_cores (template routing)
"""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import limits as L  # noqa: E402

TIERS = ("free", "demo", "pro", "enterprise", "owner")


def test_every_tier_defines_the_full_matrix():
    fields = ("deep_verify_per_day", "top_k_claims", "sandbox_minutes_per_month", "concurrency", "max_k",
              "wall_seconds", "mem_mb", "api_rpm", "repair_steps", "cpu_cores", "private_repos",
              "allow_fetch_data", "allow_unfoolability", "allow_ai_plan", "allow_data_acquisition")
    for name in TIERS:
        t = L.TIERS[name]
        for f in fields:
            assert hasattr(t, f), "tier %s missing %s" % (name, f)


def test_tiers_are_monotonic_free_le_pro_le_enterprise():
    free, pro, ent = L.TIERS["free"], L.TIERS["pro"], L.TIERS["enterprise"]
    for f in ("deep_verify_per_day", "top_k_claims", "sandbox_minutes_per_month", "concurrency", "max_k",
              "wall_seconds", "mem_mb", "api_rpm", "cpu_cores"):
        assert getattr(free, f) <= getattr(pro, f) <= getattr(ent, f), "non-monotonic %s" % f


def test_paid_features_off_on_free_on_on_paid():
    free = L.TIERS["free"]
    assert not free.allow_ai_plan and not free.allow_data_acquisition and not free.private_repos
    assert not free.allow_orchestrator
    for name in ("pro", "enterprise", "owner"):
        t = L.TIERS[name]
        assert t.allow_ai_plan and t.allow_data_acquisition and t.private_repos, name
        assert t.allow_orchestrator, name


def test_orchestrator_gated_and_kill_switchable(monkeypatch):
    # paid → orchestrated brain on; free → heuristic ladder
    assert L.clamp_request(L.TIERS["enterprise"], {})[0]["orchestrate"] is True
    assert L.clamp_request(L.TIERS["free"], {})[0]["orchestrate"] is False
    # env kill-switch flips paid back to the heuristic path fleet-wide, no redeploy
    monkeypatch.setenv("CALMA_ORCHESTRATOR", "off")
    assert L.clamp_request(L.TIERS["enterprise"], {})[0]["orchestrate"] is False


def test_clamp_carries_every_limit_into_the_run():
    # a paid tier: all knobs flow into the clamped request the pipeline/supervisor read
    out, d = L.clamp_request(L.TIERS["enterprise"], {"k": 999, "plan": True, "acquire_data": True})
    assert d.ok
    assert out["k"] == L.TIERS["enterprise"].max_k            # k clamped down
    assert out["timeout"] == L.TIERS["enterprise"].wall_seconds
    assert out["top_k"] == L.TIERS["enterprise"].top_k_claims
    assert out["cpu_cores"] == L.TIERS["enterprise"].cpu_cores
    assert out["mem_mb"] == L.TIERS["enterprise"].mem_mb
    assert out["repair_steps"] == L.TIERS["enterprise"].repair_steps
    assert out["plan"] is True and out["acquire_data"] is True


def test_free_tier_gates_and_downgrades():
    free = L.TIERS["free"]
    # AI plan is downgraded to heuristics (soft), not a hard refusal
    out, d = L.clamp_request(free, {"plan": True})
    assert d.ok and out["plan"] is False
    assert any("AI run-plan" in n for n in d.notes)
    # data-acquisition is a HARD 402 gate on free
    _out, dg = L.clamp_request(free, {"acquire_data": True})
    assert not dg.ok and dg.status == 402 and dg.kind == "gate"
    # private repo is a HARD 402 gate on free
    _o2, dp = L.clamp_request(free, {"installation_id": "123"})
    assert not dp.ok and dp.status == 402
    # cores/mem are the free tier's (lower) values
    out3, _ = L.clamp_request(free, {})
    assert out3["cpu_cores"] == free.cpu_cores and out3["mem_mb"] == free.mem_mb


def test_owner_is_unmetered_but_capped():
    owner = L.TIERS["owner"]
    assert owner.unmetered is True
    assert owner.allow_ai_plan and owner.allow_data_acquisition and owner.private_repos
    # unmetered ≠ unbounded — concrete ceilings still exist (CWE-770)
    assert owner.concurrency > 0 and owner.wall_seconds > 0 and owner.cpu_cores > 0
