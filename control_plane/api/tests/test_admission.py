"""Unit tests for admission control (no DB) — the cost/abuse backstop for untrusted execution (K6).
Monkeypatches the Postgres counts so the gate logic is tested deterministically.

Run:  ~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_admission
"""
from __future__ import annotations

import sys

from control_plane.api import config, errors, repo, service

_n = _fail = 0


def ok(cond, label):
    global _n, _fail
    _n += 1
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        _fail += 1


def admit_raises_429(tenant):
    try:
        service._admit(None, tenant)
        return False
    except errors.Problem as p:
        return p.status == 429


def admit_passes(tenant):
    try:
        service._admit(None, tenant)
        return True
    except Exception:
        return False


def _set(active_global, active_tenant, creates):
    # active count is queried twice: tenant_id=None (global) then tenant_id=<id> (per-tenant)
    repo.count_active_jobs = lambda conn, tenant_id=None, since_seconds=600: (
        active_global if tenant_id is None else active_tenant)
    repo.count_recent_creates = lambda conn, tid, since_seconds=60: creates


def main():
    t = {"id": "00000000-0000-0000-0000-000000000001", "quota": None}
    orig_a, orig_c = repo.count_active_jobs, repo.count_recent_creates
    try:
        _set(0, 0, 0)
        ok(admit_passes(t), "under all limits -> admitted")

        _set(config.MAX_CONCURRENT_GLOBAL, 0, 0)
        ok(admit_raises_429(t), "global concurrency ceiling -> 429")

        _set(0, config.MAX_CONCURRENT_PER_TENANT, 0)
        ok(admit_raises_429(t), "per-tenant concurrency cap -> 429")

        _set(0, 0, config.MAX_CREATES_PER_MIN)
        ok(admit_raises_429(t), "creation-rate cap -> 429")

        # a tenant whose quota raises max_concurrent above the default is admitted at the default count
        t2 = {"id": "00000000-0000-0000-0000-000000000002",
              "quota": {"max_concurrent": config.MAX_CONCURRENT_PER_TENANT + 5}}
        _set(0, config.MAX_CONCURRENT_PER_TENANT, 0)   # at default cap, below the override
        ok(admit_passes(t2), "tenant quota override raises the per-tenant cap")

        # the global ceiling still binds even for a high-quota tenant
        _set(config.MAX_CONCURRENT_GLOBAL, 0, 0)
        ok(admit_raises_429(t2), "global ceiling binds regardless of tenant quota")
    finally:
        repo.count_active_jobs, repo.count_recent_creates = orig_a, orig_c

    print("\n%d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
