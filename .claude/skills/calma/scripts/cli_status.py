"""calma.cli_status - the WS4 "is the guardrail on?" surface: `calma status` (the glance) and
`calma doctor` (the health check). Extracted from calma.py to separate the operator-visibility concern
from the verify pipeline + the dispatcher (clean-architecture pass: lower coupling, a real home for WS4).

Depends only on leaf modules (verdict / report / config_toml) + a DEFERRED `import calma` for the engine
version (calma.py imports THIS module for dispatch, so a top-level import would cycle). Behavior is
identical to the in-monolith version; calma.py re-exports these names so callers/tests are unchanged.
"""
from __future__ import annotations

import json
import os
import sys

import config_toml as CFG
import report as REP
import verdict as V


def _ver():
    """The engine version, fetched lazily to avoid the calma <-> cli_status import cycle."""
    import calma
    return calma.__version__


def _signing_keyid():
    """The local signing key id (Ed25519, ~/.calma/keys), or None. Best-effort - never raises."""
    kdir = os.path.expanduser(os.environ.get("CALMA_KEY_DIR", "~/.calma/keys"))
    for name in ("key.json", "signing_key.json"):
        try:
            kp = os.path.join(kdir, name)
            if os.path.isfile(kp):
                return (json.load(open(kp)) or {}).get("keyid")
        except (OSError, ValueError):
            pass
    return None


def _health_checks():
    """WS4: the environment checks behind `calma doctor` (and the guardrail line in `calma status`).
    Each entry: {key, status: ok|warn|fail, detail, fix}. Pure inspection - never mutates anything."""
    scripts = os.path.dirname(os.path.abspath(__file__))
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.realpath(
        os.path.join(scripts, "..", "..", "..", ".."))
    out = [{"key": "engine", "status": "ok", "detail": "calma %s" % _ver(), "fix": None}]
    pyv = "%d.%d.%d" % sys.version_info[:3]
    okpy = sys.version_info[:2] >= (3, 9)
    out.append({"key": "runtime", "status": "ok" if okpy else "fail",
                "detail": "Python %s%s" % (pyv, "" if okpy else "  (need >= 3.9)"),
                "fix": None if okpy else "install Python 3.9+ (calma is pure stdlib - no other deps)"})
    hooks_json = os.path.join(plugin_root, "hooks", "hooks.json")
    defined = os.path.isfile(hooks_json) and os.path.isfile(os.path.join(scripts, "hook_stop.py"))
    out.append({"key": "stop-hook", "status": "ok" if defined else "warn",
                "detail": "wired (hooks.json -> hook_stop.py)" if defined
                          else "not wired here (CLI / CI use needs no hook; the Claude Code plugin adds it)",
                "fix": None if defined else "for the zero-touch guardrail, install the calma plugin in "
                       "Claude Code (confirm with /hooks); not needed for CLI or CI verification"})
    off = os.environ.get("CALMA_HOOK") == "0" or os.environ.get("CALMA_VERIFY", "").lower() == "off"
    quiet = os.environ.get("CALMA_QUIET", "").lower() in ("1", "on", "true", "yes")
    out.append({"key": "guardrail", "status": "warn" if off else "ok",
                "detail": "opted OUT via env (CALMA_HOOK=0 / CALMA_VERIFY=off)" if off
                          else "active" + (" · per-run line quiet (CALMA_QUIET=1)" if quiet else ""),
                "fix": "unset CALMA_HOOK / CALMA_VERIFY to re-enable the guardrail" if off else None})
    kid = _signing_keyid()
    out.append({"key": "signing-key", "status": "ok" if kid else "warn",
                "detail": ("local Ed25519 key %s…" % kid[:16]) if kid
                          else "no local signing key (proofs still emit; signing is optional defense-in-depth)",
                "fix": None if kid else "calma attest keygen   # generate a local Ed25519 signing key"})
    return out


_DOCTOR_GLYPH = {"ok": "[✓]", "warn": "[!]", "fail": "[✗]"}
_DOCTOR_RANK = {"ok": 0, "warn": 1, "fail": 2}


def doctor_cmd(*, fix=False, as_json=False):
    """WS4: `calma doctor` - environment health. [✓]/[!]/[✗] per check + a fix line on every non-OK
    one; --fix applies the safe auto-fixes (today: generate a local signing key). Answers 'is the
    guardrail wired and working?' (the Homebrew/Flutter/Expo doctor convention)."""
    checks = _health_checks()
    if fix:
        for c in checks:
            if c["key"] == "signing-key" and c["status"] != "ok":
                try:
                    import attest as ATT
                    ATT.keygen()
                    print("fixed: generated a local signing key")
                except Exception as e:  # keygen is optional; never let --fix crash doctor
                    print("could not auto-generate a signing key: %s" % e, file=sys.stderr)
        checks = _health_checks()   # re-evaluate after fixes
    if as_json:
        ok = all(c["status"] != "fail" for c in checks)
        print(json.dumps({"checks": checks, "ok": ok}, indent=2))
        return 0 if ok else 1
    print("calma doctor")
    worst = 0
    for c in checks:
        print("  %s %-13s %s" % (_DOCTOR_GLYPH[c["status"]], c["key"], c["detail"]))
        if c["status"] != "ok" and c["fix"]:
            print("       ↳ %s" % c["fix"])
        worst = max(worst, _DOCTOR_RANK[c["status"]])
    nfail = sum(1 for c in checks if c["status"] == "fail")
    nwarn = sum(1 for c in checks if c["status"] == "warn")
    if worst == 0:
        print("\nall good - the guardrail is wired and ready.")
    else:
        tip = "" if fix else "  (run `calma doctor --fix` to auto-fix what's safe)"
        print("\n%d issue(s), %d warning(s) - see the fix lines above.%s" % (nfail, nwarn, tip))
    return 0 if nfail == 0 else 1


def status_cmd(target=".", *, as_json=False):
    """WS4: the glance command. Is the guardrail on, is it working, and what has it checked? - answered
    in ONE command: hook + signing-key state, this project's 7-day verdict tally, and the last run."""
    import time
    target = os.path.abspath(target)
    cfg = CFG.verify_config(target)
    vtarget = cfg["target"] if cfg else target
    checks = {c["key"]: c for c in _health_checks()}
    hist = []
    hpath = os.path.join(vtarget, ".calma", "history.jsonl")
    if os.path.isfile(hpath):
        for line in open(hpath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):   # a hand-edited line that is valid JSON but not an object
                    hist.append(obj)         # (a bare array/scalar) must not crash the .get() below
    verifs = [h for h in hist if h.get("run_id") != "teardown"]
    now = int(time.time())
    last7 = [h for h in verifs if now - int(h.get("ts", 0) or 0) <= 7 * 86400]

    def _entry_outcome(h):
        # prefer the persisted REAL gate exit (so a CONFIRMED-with-open-blocker run tallies as Caught,
        # matching the gate); fall back to the verdict word only for pre-fix history records.
        v = h.get("verdict", "?")
        ec = h.get("gate_exit")
        if ec is None:
            ec = 0 if v in (V.CONFIRMED, V.CAVEATS) else 2 if v == V.INCONCLUSIVE else 1
        return V.outcome(v, ec)

    tally = {V.CONFIRMED_OUTCOME: 0, V.CAUGHT_OUTCOME: 0, V.CANT_TELL_OUTCOME: 0}
    for h in last7:
        tally[_entry_outcome(h)] += 1
    last = verifs[-1] if verifs else None
    if as_json:
        print(json.dumps({"guardrail": {k: checks[k]["status"] for k in checks},
                          "signing_keyid": _signing_keyid(), "project": vtarget,
                          "last7": tally, "checks_total": len(last7),
                          "last_run": last}, indent=2, default=str))
        return 0
    g, sk = checks["guardrail"], checks["signing-key"]
    hook_ok = checks["stop-hook"]["status"] == "ok" and g["status"] == "ok"
    # the guardrail line: coherent glyph + detail. Active when the hook is wired and not opted-out;
    # otherwise show the actual reason (opted-out, or hook-not-wired for a CLI/CI-only install).
    if hook_ok:
        grail = "stop-hook active"
    elif g["status"] != "ok":
        grail = g["detail"]                       # opted out via env
    else:
        grail = checks["stop-hook"]["detail"]     # hook not wired here (CLI/CI install)
    print("calma status")
    print("  guardrail   %s %s" % ("[✓]" if hook_ok else "[!]", grail))
    print("  signing     %s" % (sk["detail"]))
    print("  engine      calma %s · Python %d.%d" % (_ver(), *sys.version_info[:2]))
    rel = os.path.relpath(vtarget)
    print("  project     %s%s" % (rel, "  (calma.toml: %s)" % cfg.get("metric")
                                  if cfg and cfg.get("metric") else ""))
    if last7 or verifs:
        total = len(last7)
        parts = ["%d %s" % (tally[o], o) for o in (V.CONFIRMED_OUTCOME, V.CAUGHT_OUTCOME,
                                                   V.CANT_TELL_OUTCOME) if tally[o]]
        print("  last 7 days %d check%s%s" % (total, "" if total == 1 else "s",
              "  ·  " + " · ".join(parts) if parts else ""))
        # the promise made legible: with the guardrail on, every number the agent emitted got checked.
        caught = tally[V.CAUGHT_OUTCOME]
        print("  shipped     %d number%s caught before shipping%s"
              % (caught, "" if caught == 1 else "s",
                 "  ·  0 shipped unverified" if hook_ok else ""))
        if last:
            ago = _ago(now - int(last.get("ts", now) or now))
            oc = _entry_outcome(last)
            mv = REP.fmt_value(last.get("recomputed"), last.get("metric"))
            print("  last run    %s %s %s  ·  %s" % (oc, last.get("metric") or "", mv, ago))
    else:
        print("  history     no verifications in this project yet - run `calma up`")
    print("  → calma doctor   full health check (+ --fix)")
    return 0


def _ago(secs):
    """A terse 'N{s,m,h,d} ago' for a delta in seconds."""
    secs = max(0, int(secs))
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= n:
            return "%d%s ago" % (secs // n, unit)
    return "%ds ago" % secs
