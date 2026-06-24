"""execprovider._selfcheck — a standalone conformance smoke for the LocalProvider against the LIVE engine.

This is deliberately NOT named test_*.py: it must NOT be picked up by tests/run_all.py (which globs test_*.py)
so the core suite count stays exactly 71. Run it manually:

    python3 .claude/skills/calma/scripts/execprovider/_selfcheck.py

It proves the abstraction fits the real engine on THIS host: LocalProvider(isolation="auto") drives
run_hermetic, returns a conformant RunResult on a VERIFIED tier (seatbelt-verified on macOS / bwrap-verified on
Linux), with network_run=="off", an artifacts_manifest hashed host-side, a determinism_digest, and a measured
wall_seconds. It also checks isinstance(provider, ExecutionProvider) (the runtime_checkable Protocol) and that a
second identical run reproduces the determinism_digest (the M1.6 reproducibility property, in miniature).
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# import the package by its parent so `from execprovider import ...` resolves
if os.path.dirname(SCRIPTS) not in sys.path:
    sys.path.insert(0, os.path.dirname(SCRIPTS))

from execprovider import (CodeBundle, ExecutionProvider, LocalProvider, ResourceLimits,
                          RunSpec, TemplateSpec, verified_tiers)

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if cond:
        print("  ok   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s" % label)


def make_bundle(base):
    """A trivial pure-stdlib entrypoint that writes one small artifact into runs/ — exercises the manifest +
    a controlled-to-bit determinism classification (no RNG/GPU/subprocess imports)."""
    src = (
        "import os, json\n"
        "os.makedirs('runs', exist_ok=True)\n"
        "with open(os.path.join('runs', 'out.json'), 'w') as fh:\n"
        "    json.dump({'metric': 'sum', 'value': 6}, fh, sort_keys=True)\n"
        "print('SELFCHECK_OK value=6')\n"
    )
    with open(os.path.join(base, "main.py"), "w") as fh:
        fh.write(src)
    return CodeBundle(uri="file://" + base, sha256="", entrypoint="main.py", language="python")


def run_once(prov, base):
    spec = RunSpec(
        run_id="01J-SELFCHECK",
        recipe_id="analytics.sum", recipe_version="1.0.0",
        template=TemplateSpec(template_id="python-3.x", language="python"),
        bundle=make_bundle(base),
        limits=ResourceLimits(wall_seconds=30),
        trust="own-code",   # own-code so the host Seatbelt/bwrap tier verifies (no container needed)
    )
    prepared = prov.prepare(spec.template)
    try:
        return prov.run(spec, prepared)
    finally:
        prov.teardown(prepared)


def main():
    prov = LocalProvider(isolation="auto")
    truth(isinstance(prov, ExecutionProvider),
          "LocalProvider satisfies the ExecutionProvider Protocol (runtime_checkable)")

    avail, why = prov.available()
    truth(avail, "auto provider reports available (%s)" % (why or "ok"))

    base1 = tempfile.mkdtemp(prefix="calma_selfcheck_")
    res = run_once(prov, base1)

    print("  -- RunResult: tier=%s verified=%s exit=%s net=%s det=%s wall=%ss artifacts=%d"
          % (res.isolation_tier, res.tier_verified, res.exit_code, res.network_run,
             res.determinism_mode, res.resource_usage.wall_seconds, len(res.artifacts_manifest)))

    truth(res.run_id == "01J-SELFCHECK", "RunResult carries the run_id")
    truth(res.exit_code == 0, "exit_code == 0 (the entrypoint ran cleanly)")
    truth(res.isolation_tier in verified_tiers(),
          "isolation_tier %r is a VERIFIED tier" % res.isolation_tier)
    truth(res.tier_verified is True, "tier_verified is True")
    truth(res.network_run == "off", "network_run == 'off' (egress proven denied by the in-tier probe)")
    truth("SELFCHECK_OK" in res.stdout_tail, "stdout tail captured the entrypoint output")
    truth(len(res.artifacts_manifest) == 1 and res.artifacts_manifest[0].name == "out.json",
          "artifacts_manifest hashed the produced artifact host-side (NEW field, doc §5-E)")
    truth(len(res.determinism_digest) == 64, "determinism_digest computed (sha256, NEW field, doc §5-G)")
    truth(res.resource_usage.wall_seconds is not None and res.resource_usage.wall_seconds >= 0,
          "resource_usage.wall_seconds measured by the provider layer (doc §5-C)")
    truth(res.determinism_mode == "controlled-to-bit",
          "pure-stdlib entrypoint classified controlled-to-bit")

    # reproducibility (M1.6 in miniature): a second identical run -> identical determinism_digest
    base2 = tempfile.mkdtemp(prefix="calma_selfcheck_")
    res2 = run_once(prov, base2)
    truth(res2.determinism_digest == res.determinism_digest,
          "two runs of one RunSpec reproduce the determinism_digest")

    print("\n%d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
