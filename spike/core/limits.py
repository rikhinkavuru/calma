"""calma.spike.core.limits — tiered rate limits, usage quotas, and feature gates (PRICING.md, made real).

The economic reality (PRICING.md): Calma *re-executes the world's computations* — every deep verify burns
sandbox compute + inference. So the meters are not an afterthought, they're admission control on the one
expensive thing. This module encodes the pricing tiers and enforces them **before a sandbox is ever
provisioned**, fail-closed:

  meter the expensive thing (deep-verify scans, sandbox-minutes), keep the cheap thing (discovery) generous.

Design rules that keep this safe and cheap:
  * Pure stdlib, thread-safe (a single lock; the deploy is a single in-memory instance — the control plane is
    the durable store later). No new dependency, no network, ~zero overhead per call.
  * FCR-safe by construction: a limit can only make a verdict *less* confident (refuse a run, or cap deep
    verification to the top-K claims so the rest stay DISCOVERED). It can never turn a wrong number green.
    The verdict taxonomy is identical on every tier — tiers gate *how much / how deep*, never *whether a
    wrong number slips through* (PRICING.md invariant).
  * Clamp, don't crash: an over-limit *knob* (k too high, deep on a claim past top-K) is clamped down with an
    explanatory note; an over-limit *scan* (daily quota, sandbox budget) or a forbidden *feature* (private
    repo on free) is refused with a clear, actionable reason + a Retry-After where time-based.

The numbers are PRICING.md's proposed defaults, overridable by env so the founder can loosen them as the
flywheel drives cost-per-scan down without a redeploy.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field

# ── tier definitions (PRICING.md "Rate limits — per tier") ──────────────────────────────────────────────────
# `owner` is the local-first operator (their own machine, their own keys — the token is UNSET): unmetered.
# `enterprise` is contract-bounded; we still set generous concrete ceilings so "unlimited" is never literally
# unbounded (a CWE-770 guardrail — an unbounded resource is a DoS primitive even for a trusted caller).


@dataclass(frozen=True)
class Tier:
    name: str
    deep_verify_per_day: int          # scans that actually re-execute (the primary meter)
    top_k_claims: int                 # claims deep-verified per scan (top-K by salience); rest stay DISCOVERED
    sandbox_minutes_per_month: int    # the COGS meter (E2B microVM minutes)
    concurrency: int                  # parallel deep verifies per tenant (bounds fan-out; CWE-770)
    max_k: int                        # runs-per-repo ceiling (determinism depth)
    wall_seconds: int                 # per-sandbox wall-clock cap
    mem_mb: int                       # per-sandbox RSS cap (advisory hint; the supervisor is authoritative)
    api_rpm: int                      # requests/min (burst control)
    repair_steps: int                 # feature-1 env-repair budget (0 = feature off)
    retention_days: int               # history retention
    private_repos: bool               # connect + verify private repos (via a GitHub App installation)
    allow_fetch_data: bool            # opt-in external-data pull (paid/opt-in only; SSRF-guarded downstream)
    allow_unfoolability: bool         # fuzz / metamorphic / perturbation extra-run anti-cheat (F2/F7/F10)
    unmetered: bool = False           # the local operator: no counters drawn down


def _i(env: str, default: int) -> int:
    v = (os.environ.get(env) or "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


# Concrete defaults straight from PRICING.md's table; each is an env knob so limits loosen without a redeploy.
TIERS: dict[str, Tier] = {
    "free": Tier(
        name="free",
        deep_verify_per_day=_i("CALMA_FREE_SCANS_PER_DAY", 5),
        top_k_claims=_i("CALMA_FREE_TOP_K", 3),
        sandbox_minutes_per_month=_i("CALMA_FREE_SANDBOX_MIN", 30),
        concurrency=_i("CALMA_FREE_CONCURRENCY", 1),
        max_k=_i("CALMA_FREE_MAX_K", 2),
        wall_seconds=_i("CALMA_FREE_WALL_S", 300),
        mem_mb=_i("CALMA_FREE_MEM_MB", 1024),
        api_rpm=_i("CALMA_FREE_API_RPM", 30),
        repair_steps=0,
        retention_days=7,
        private_repos=False,
        allow_fetch_data=False,
        allow_unfoolability=False,
    ),
    "pro": Tier(
        name="pro",
        deep_verify_per_day=_i("CALMA_PRO_SCANS_PER_DAY", 100),
        top_k_claims=_i("CALMA_PRO_TOP_K", 25),
        sandbox_minutes_per_month=_i("CALMA_PRO_SANDBOX_MIN", 600),
        concurrency=_i("CALMA_PRO_CONCURRENCY", 5),
        max_k=_i("CALMA_PRO_MAX_K", 10),
        wall_seconds=_i("CALMA_PRO_WALL_S", 1200),
        mem_mb=_i("CALMA_PRO_MEM_MB", 4096),
        api_rpm=_i("CALMA_PRO_API_RPM", 300),
        repair_steps=_i("CALMA_PRO_REPAIR_STEPS", 4),
        retention_days=90,
        private_repos=True,
        allow_fetch_data=False,
        allow_unfoolability=True,
    ),
    "enterprise": Tier(
        name="enterprise",
        deep_verify_per_day=_i("CALMA_ENT_SCANS_PER_DAY", 5000),
        top_k_claims=_i("CALMA_ENT_TOP_K", 100000),
        sandbox_minutes_per_month=_i("CALMA_ENT_SANDBOX_MIN", 100000),
        concurrency=_i("CALMA_ENT_CONCURRENCY", 10),
        max_k=_i("CALMA_ENT_MAX_K", 50),
        wall_seconds=_i("CALMA_ENT_WALL_S", 3600),
        mem_mb=_i("CALMA_ENT_MEM_MB", 16384),
        api_rpm=_i("CALMA_ENT_API_RPM", 3000),
        repair_steps=_i("CALMA_ENT_REPAIR_STEPS", 12),
        retention_days=3650,
        private_repos=True,
        allow_fetch_data=True,
        allow_unfoolability=True,
    ),
    # the local-first operator (token unset): their machine, their keys — unmetered but still concrete-capped so
    # a runaway loop can't fan out unbounded.
    "owner": Tier(
        name="owner",
        deep_verify_per_day=10_000_000,
        top_k_claims=1_000_000,
        sandbox_minutes_per_month=10_000_000,
        concurrency=_i("CALMA_OWNER_CONCURRENCY", 8),
        max_k=1000,
        wall_seconds=_i("CALMA_OWNER_WALL_S", 3600),
        mem_mb=_i("CALMA_OWNER_MEM_MB", 65536),
        api_rpm=1_000_000,
        repair_steps=100,
        retention_days=3650,
        private_repos=True,
        allow_fetch_data=True,
        allow_unfoolability=True,
        unmetered=True,
    ),
}

_DEFAULT_TIER = (os.environ.get("CALMA_TIER_DEFAULT") or "free").strip().lower()


def resolve_tier(name: str | None) -> Tier:
    """Map a caller-supplied tier name to a concrete Tier, defaulting to the configured public default (`free`)
    for anything unknown/absent. Unknown → the *most* restrictive default: fail closed on identity too."""
    key = (name or "").strip().lower()
    return TIERS.get(key) or TIERS.get(_DEFAULT_TIER) or TIERS["free"]


# ── decision types ──────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Decision:
    """The outcome of an admission check. `ok=False` → refuse the request with `status`/`reason`
    (+`retry_after` for time-based limits). `notes` records every clamp that was applied so the caller can
    surface an honest 'we ran a smaller job than you asked' message."""
    ok: bool = True
    status: int = 200                 # HTTP-ish: 429 rate/quota, 402 upgrade-required, 400 bad request
    reason: str = ""
    retry_after: int | None = None    # seconds
    kind: str = ""                    # api_rate | daily | sandbox | concurrency | gate — lets the caller pick
    #                                   the right behaviour (downgrade-to-discovery vs refuse-and-retry)
    notes: list[str] = field(default_factory=list)


# ── the limiter ─────────────────────────────────────────────────────────────────────────────────────────────
# Simple, correct primitives (no external store needed for a single in-memory instance):
#   * API rate  — a fixed 60s window counter per tenant (burst control; a token bucket's smoothing isn't worth
#                 the extra state here).
#   * daily scans / monthly sandbox-minutes — calendar-anchored fixed windows (UTC day / month), so the quota
#                 resets predictably at midnight/month-start rather than a rolling 24h that punishes a burst.
#   * concurrency — a live in-flight counter per tenant, incremented at admission, decremented on completion.
# All keyed by a tenant id (the WorkOS user/org, passed by the trusted first-party proxy).


def _day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _month_key(now: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(now))


class Limiter:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._api: dict[str, tuple[int, int]] = {}          # tenant -> (window_start_epoch_min, count)
        self._scans: dict[tuple[str, str], int] = {}        # (tenant, day) -> deep-verify count
        self._sandbox: dict[tuple[str, str], float] = {}    # (tenant, month) -> sandbox seconds used
        self._inflight: dict[str, int] = {}                 # tenant -> live deep verifies

    # -- API burst rate --------------------------------------------------------------------------------------
    def check_api_rate(self, tenant: str, tier: Tier) -> Decision:
        if tier.unmetered:
            return Decision(ok=True)
        now = self._clock()
        window = int(now // 60)
        with self._lock:
            w, c = self._api.get(tenant, (window, 0))
            if w != window:
                w, c = window, 0
            c += 1
            self._api[tenant] = (w, c)
            over = c > tier.api_rpm
        if over:
            retry = 60 - int(now % 60)
            return Decision(ok=False, status=429, retry_after=max(1, retry), kind="api_rate",
                            reason="rate limit: %d requests/min on the %s tier — retry in %ds"
                                   % (tier.api_rpm, tier.name, max(1, retry)))
        return Decision(ok=True)

    # -- deep-verify admission (daily scan quota + monthly sandbox budget + concurrency) ----------------------
    def admit_scan(self, tenant: str, tier: Tier) -> Decision:
        """Called right before a deep verify is dispatched. Checks the daily scan quota and the monthly
        sandbox-minute budget, and reserves a concurrency slot. On success the caller MUST later call
        `release_slot` + `record_sandbox_seconds`. Discovery-only scans do not call this (they're ~free)."""
        if tier.unmetered:
            with self._lock:
                self._inflight[tenant] = self._inflight.get(tenant, 0) + 1
            return Decision(ok=True)
        now = self._clock()
        day, month = _day_key(now), _month_key(now)
        with self._lock:
            used_today = self._scans.get((tenant, day), 0)
            if used_today >= tier.deep_verify_per_day:
                return Decision(ok=False, status=429, retry_after=_seconds_to_midnight(now), kind="daily",
                                reason="daily deep-verify quota reached (%d/day on the %s tier) — discovery "
                                       "still runs; upgrade or retry tomorrow"
                                       % (tier.deep_verify_per_day, tier.name))
            used_min = self._sandbox.get((tenant, month), 0.0) / 60.0
            if used_min >= tier.sandbox_minutes_per_month:
                return Decision(ok=False, status=402, kind="sandbox",
                                reason="monthly sandbox-minute budget exhausted (%d min on the %s tier) — "
                                       "discovery still runs; upgrade for more re-execution"
                                       % (tier.sandbox_minutes_per_month, tier.name))
            inflight = self._inflight.get(tenant, 0)
            if inflight >= tier.concurrency:
                return Decision(ok=False, status=429, retry_after=10, kind="concurrency",
                                reason="concurrency limit reached (%d parallel verifies on the %s tier) — "
                                       "the running scans must finish first"
                                       % (tier.concurrency, tier.name))
            # reserve
            self._scans[(tenant, day)] = used_today + 1
            self._inflight[tenant] = inflight + 1
        return Decision(ok=True)

    def release_slot(self, tenant: str) -> None:
        with self._lock:
            n = self._inflight.get(tenant, 0)
            if n > 0:
                self._inflight[tenant] = n - 1

    def record_sandbox_seconds(self, tenant: str, seconds: float) -> None:
        if not seconds or seconds <= 0:
            return
        now = self._clock()
        month = _month_key(now)
        with self._lock:
            self._sandbox[(tenant, month)] = self._sandbox.get((tenant, month), 0.0) + float(seconds)

    # -- observability ---------------------------------------------------------------------------------------
    def usage(self, tenant: str, tier: Tier) -> dict:
        now = self._clock()
        day, month = _day_key(now), _month_key(now)
        with self._lock:
            scans = self._scans.get((tenant, day), 0)
            sandbox_s = self._sandbox.get((tenant, month), 0.0)
            inflight = self._inflight.get(tenant, 0)
        return {
            "tier": tier.name,
            "scans_today": scans,
            "scans_per_day": tier.deep_verify_per_day,
            "sandbox_minutes_used": round(sandbox_s / 60.0, 2),
            "sandbox_minutes_per_month": tier.sandbox_minutes_per_month,
            "inflight": inflight,
            "concurrency": tier.concurrency,
        }


def _seconds_to_midnight(now: float) -> int:
    lt = time.gmtime(now)
    return max(1, (24 - lt.tm_hour) * 3600 - lt.tm_min * 60 - lt.tm_sec)


# ── request clamping + feature gates ────────────────────────────────────────────────────────────────────────
# A plain PyPI requirement spec: name + optional extras + optional version constraint. Everything else (flags
# like --index-url, VCS/URL refs git+https://…, local paths, shell/pip metacharacters) is REFUSED. The repo's
# own requirements.txt is installed faithfully (strict) elsewhere; THIS gate only screens the *tolerant* deps
# that come from an LLM plan or the API caller — the prompt-injection → pip-arg-injection path.
_PIP_SPEC = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"          # PyPI project name
    r"(\[[A-Za-z0-9,._-]+\])?"              # optional extras, e.g. [standard]
    r"((==|>=|<=|~=|!=|<|>)[A-Za-z0-9][A-Za-z0-9.\-_*+!]*)?$"  # optional version constraint, no whitespace
)


def is_safe_pip_spec(arg) -> bool:
    """True iff `arg` is a plain, single PyPI requirement spec safe to hand to `pip install` — no flags, URLs,
    VCS refs, local paths, whitespace-separated tokens, or shell/pip metacharacters. Length-bounded."""
    return isinstance(arg, str) and 0 < len(arg) <= 128 and bool(_PIP_SPEC.match(arg.strip()))


def sanitize_pip(specs) -> list[str]:
    """Drop any dep that isn't a plain PyPI spec. Used on LLM-planned and API-supplied (tolerant) deps so a
    prompt-injected or malicious plan can't smuggle `--index-url http://evil/` or `git+https://evil` into the
    installer. Order-preserving, de-duplicated."""
    out, seen = [], set()
    for s in specs or []:
        if is_safe_pip_spec(s):
            key = s.strip()
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def clamp_request(tier: Tier, req: dict) -> tuple[dict, Decision]:
    """Clamp a verify request to the tier, in place-safe fashion (returns a new dict + a Decision).

    Two kinds of enforcement:
      * CLAMP (soft) — a knob that's merely too big is quietly reduced (k, wall) with a note. Running a smaller
        job than asked is honest and still fail-closed.
      * GATE (hard) — a capability the tier does not include (private repo, external-data fetch) is REFUSED
        with status 402 so the user gets a clear upgrade path instead of a silently different result.

    `deep` itself is never gated off — every tier can deep-verify; the *count* is metered by admit_scan. The
    top-K claim cap is returned as `top_k` for the pipeline to apply (claims past K stay DISCOVERED).
    """
    d = Decision(ok=True)
    out = dict(req)

    # k — runs per repo (determinism depth)
    k = out.get("k")
    if isinstance(k, int) and k > tier.max_k:
        out["k"] = tier.max_k
        d.notes.append("k clamped %d→%d (%s tier)" % (k, tier.max_k, tier.name))

    # per-sandbox wall-clock
    out["timeout"] = tier.wall_seconds
    out["top_k"] = tier.top_k_claims
    out["repair_steps"] = tier.repair_steps

    # feature GATES — refuse, don't silently downgrade
    if out.get("fetch_data") and not tier.allow_fetch_data:
        return out, Decision(ok=False, status=402, kind="gate",
                             reason="external-data fetch is an opt-in paid capability — not on the %s tier"
                                    % tier.name)
    if out.get("installation_id") and not tier.private_repos:
        return out, Decision(ok=False, status=402, kind="gate",
                             reason="connecting private repos (GitHub App installs) requires a paid tier — "
                                    "the %s tier verifies public repos" % tier.name)
    if out.get("fuzz") and not tier.allow_unfoolability:
        out["fuzz"] = False
        d.notes.append("un-foolability extra runs (fuzz/metamorphic) are a paid capability — disabled")
    if out.get("repair") and tier.repair_steps <= 0:
        out["repair"] = False
        d.notes.append("the env-repair agent is a paid capability — disabled")

    return out, d


_LIMITER: Limiter | None = None


def get_limiter() -> Limiter:
    """Process-wide singleton limiter (the single in-memory instance's counters)."""
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = Limiter()
    return _LIMITER
