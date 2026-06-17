"""Benchmark arm: a code-running LLM AGENT (the honest comparison to Calma).

The existing `LLM-as-judge` arm gets NO code execution. This arm gives a strong agent the result
DATA + the claim + a `run_python` tool, K times per case, and records whether it called the claim
honest/flawed/abstain. The point is NOT raw catch-rate (a good agent gets most simple recomputes
right) but the residual gaps that survive once it CAN execute:
  - verdict INSTABILITY across the K reruns   (Calma = 0 by construction)
  - validity-blindness: on leakage/overfitting/realism/contamination cases the NUMBER reproduces,
    so an agent that just recomputes says honest and MISSES the invalidity
  - false-alarms with no calibrated tolerance, and $ + latency vs Calma's ~0.2s/$0/offline

Two backends:
  --mock           deterministic local recompute (no API key, no network) - validates the plumbing
                   + scoring offline. NOT a real agent; do not report mock numbers as results.
  (default)        a real agent via the Anthropic Messages API (urllib, stdlib) with a run_python
                   tool. Needs ANTHROPIC_API_KEY. Steelman it: strong model + an explicit
                   "recompute AND check validity" system prompt (below).

Writes results/agent.json: [{id, prediction, recomputed, ms, usd, reruns:[...]}] - same shape
run_calma.py emits, plus reruns/usd. score.py picks it up automatically when the file exists.

Run:
  python3 benchmark/run_agent.py --mock --limit 8        # offline plumbing check
  ANTHROPIC_API_KEY=... python3 benchmark/run_agent.py --k 5 --model claude-opus-4-8
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
REPO = os.path.realpath(os.path.join(HERE, ".."))
sys.path.insert(0, SKILL)
import run_hermetic as H  # noqa: E402  reuse the engine's OWN network-off sandbox for the agent's code tool

# steelman system prompt - the arm is only fair if the agent is told to do the right thing.
SYSTEM = (
    "You verify a computational result. You are given a metric, a natural-language claim, and one or "
    "more raw output data files. Use the run_python tool to RECOMPUTE the metric from the raw files "
    "and decide whether the claim is honest (matches the data) or flawed (materially wrong). Before "
    "answering, also consider validity: data leakage (train/test overlap), backtest overfitting "
    "(selection over many trials), unrealistic execution (costs/slippage make a 'net' number gross), "
    "and eval/benchmark contamination - any of which can make a number that reproduces still invalid. "
    "When done, reply with ONLY a JSON object: "
    '{"verdict":"honest|flawed|abstain","recomputed":<number or null>,"why":"<one line>"}. '
    "Use abstain only when you genuinely cannot decide (it is a safe non-answer, never a wrong one)."
)

# rough Anthropic prices (USD per 1M tokens); update as needed. Only used for the cost column.
_PRICES = {"claude-opus-4-8": (15.0, 75.0), "claude-sonnet-4-6": (3.0, 15.0),
           "claude-haiku-4-5": (0.80, 4.0)}


# ---- the agent's code tool runs in the engine's OWN network-off sandbox ----
# Capability-vs-capability: the agent executes its run_python code under the SAME isolation Calma uses
# (Seatbelt on macOS, bubblewrap on Linux) - network OFF, $HOME/secrets unreadable, writes confined to
# the per-case work dir, each tool call its own process (DS-1000 global-state lesson). A host that
# can't verify isolation is stamped host-not-isolated and its runs are DROPPED from the scored result -
# never run untrusted agent code unsandboxed, never silently report an unsandboxed number.
_TIER = None


def _detect_tier():
    """Detect (once) the verified network-off tier on this host via the engine's positive-control
    self-test (a planted secret-read AND an egress attempt must BOTH fail). 'host-not-isolated' when no
    tier verifies."""
    global _TIER
    if _TIER is None:
        try:
            if sys.platform == "darwin":
                _TIER = H.doctor(REPO).get("tier", "host-not-isolated")
            elif sys.platform.startswith("linux"):
                _TIER = H.bwrap_doctor(REPO).get("tier", "host-not-isolated")
            else:
                _TIER = "host-not-isolated"
        except Exception:  # any probe failure is a non-isolated host, never a silent verified stamp
            _TIER = "host-not-isolated"
    return _TIER


def _sandboxed_run(code, work, timeout=30):
    """Run agent-written `code` network-off, confined to `work`, in the detected verified tier. Returns
    (output_str_or_None, tier). output is None ONLY when the host can't isolate (the caller refuses to
    run the code and excludes the run)."""
    tier = _detect_tier()
    argv = [sys.executable, "-c", code]
    work = os.path.realpath(work)
    if tier == "seatbelt-verified":
        rc, out, err, killed = H._run_sandboxed(H._profile(work), argv, cwd=work, timeout=timeout)
        return (("[timeout]" if killed else "") + (out or "") + (err or ""))[-4000:], tier
    if tier == "bwrap-verified":
        try:
            p = subprocess.run(H._bwrap_argv(work, argv), cwd=work, capture_output=True,
                               text=True, timeout=timeout)
            return (p.stdout + p.stderr)[-4000:], tier
        except subprocess.SubprocessError as e:
            return ("error: %s" % e)[-4000:], tier
    return None, "host-not-isolated"  # refuse to run untrusted code unsandboxed


# ---- data materialization -------------------------------------------------

def _entrypoint(case_dir):
    """How to (re)produce the case's data. Synthetic cases ship a gen.py; others declare an
    entrypoint in verify.yaml. We never show the agent this code - only the data it emits."""
    if os.path.exists(os.path.join(case_dir, "gen.py")):
        return [sys.executable, "gen.py"]
    vy = os.path.join(case_dir, "verify.yaml")
    if os.path.exists(vy):
        try:
            ep = (json.load(open(vy)).get("run") or {}).get("entrypoint")
        except (ValueError, OSError):
            ep = None
        if ep and ep.endswith(".py"):
            return [sys.executable, ep]
    return None


def _ensure_data(case):
    """Make sure the artifact exists (run the entrypoint once if needed). Returns the artifact
    path, or None if it can't be produced (the agent then abstains)."""
    art = os.path.join(case["dir"], case["artifact"])
    if os.path.exists(art):
        return art
    ep = _entrypoint(case["dir"])
    if not ep:
        return None
    try:
        subprocess.run(ep, cwd=case["dir"], capture_output=True, timeout=120, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    return art if os.path.exists(art) else None


# ---- mock agent (deterministic, offline) ----------------------------------

def _read_cols(path):
    with open(path, newline="") as f:
        rd = csv.reader(f)
        header = next(rd, [])
        cols = {h: [] for h in header}
        for row in rd:
            for h, v in zip(header, row):
                cols[h].append(v)
    return cols


def _floats(xs):
    out = []
    for x in xs:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _mock_recompute(metric, cols):
    """A tiny stdlib recompute for a few metric families - enough to exercise the harness with a
    realistic spread. Unknown metrics -> None (the mock abstains). This is plumbing, not a real agent."""
    names = {h.lower(): h for h in cols}
    def col(*cands):
        for c in cands:
            if c in names:
                return _floats(cols[names[c]])
        return None
    if metric in ("accuracy",):
        yt, yp = col("y_true", "label"), col("y_pred", "pred")
        if yt and yp:
            return sum(1 for a, b in zip(yt, yp) if a == b) / len(yt)
    if metric in ("mean", "column_mean"):
        v = col("value", "x")
        if v:
            return sum(v) / len(v)
    if metric in ("sum", "total"):
        v = col("value", "x", "amount")
        if v:
            return sum(v)
    if metric in ("rmse", "mae"):
        yt, yp = col("y_true", "actual"), col("y_pred", "pred")
        if yt and yp:
            d = [a - b for a, b in zip(yt, yp)]
            return (sum(e * e for e in d) / len(d)) ** 0.5 if metric == "rmse" else sum(abs(e) for e in d) / len(d)
    return None


def _mock_agent(case, art):
    """Deterministic: recompute if we can, compare to the claim under a 5% band, else abstain."""
    if not art:
        return {"verdict": "abstain", "recomputed": None, "why": "no data"}
    try:
        got = _mock_recompute(case["metric"], _read_cols(art))
    except (OSError, ValueError, ZeroDivisionError):
        got = None
    if got is None:
        return {"verdict": "abstain", "recomputed": None, "why": "metric not implemented in mock"}
    claim = float(case["claim"])
    band = 0.05 * max(abs(claim), 1e-9)
    verdict = "honest" if abs(got - claim) <= band else "flawed"
    return {"verdict": verdict, "recomputed": round(got, 6), "why": "mock recompute"}


# ---- real agent (Anthropic Messages API via urllib) -----------------------

def _anthropic_agent(case, art, model, max_turns=8):
    """A real code-running agent. Returns (parsed_verdict_dict, usd). Requires ANTHROPIC_API_KEY."""
    import urllib.request
    key = os.environ["ANTHROPIC_API_KEY"]
    work = os.path.join(case["dir"], ".agent_work")
    os.makedirs(work, exist_ok=True)
    # opaque copy of the artifact (don't leak which case / the generator)
    data_name = "data" + os.path.splitext(art)[1]
    with open(art, "rb") as src, open(os.path.join(work, data_name), "wb") as dst:
        dst.write(src.read())

    tools = [{"name": "run_python", "description": "Run Python in the data directory; prints go to stdout.",
              "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}]
    user = ("metric: %s\nclaim: %s\nfile in your working dir: %s\nRecompute the metric from %s and decide."
            % (case["metric"], case["claim_text"], data_name, data_name))
    messages = [{"role": "user", "content": user}]
    in_tok = out_tok = 0

    def _post(body):
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    for _ in range(max_turns):
        resp = _post({"model": model, "max_tokens": 2048, "system": SYSTEM, "tools": tools, "messages": messages})
        u = resp.get("usage", {})
        in_tok += u.get("input_tokens", 0); out_tok += u.get("output_tokens", 0)
        content = resp.get("content", [])
        messages.append({"role": "assistant", "content": content})
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if not tool_uses:
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            pin, pout = _PRICES.get(model, (3.0, 15.0))
            usd = in_tok / 1e6 * pin + out_tok / 1e6 * pout
            return _parse_verdict(text), usd, _transcript(model, SYSTEM, messages)
        results = []
        for tu in tool_uses:
            code = (tu.get("input") or {}).get("code", "")
            out, tier = _sandboxed_run(code, work)  # network-off, confined to `work`
            if out is None:  # host can't isolate -> refuse to run untrusted code (the run is excluded)
                out = "error: this host could not verify a network-off sandbox; tool execution refused"
            results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": out})
        messages.append({"role": "user", "content": results})
    pin, pout = _PRICES.get(model, (3.0, 15.0))
    return ({"verdict": "abstain", "recomputed": None, "why": "max turns"},
            in_tok / 1e6 * pin + out_tok / 1e6 * pout, _transcript(model, SYSTEM, messages))


def _transcript(model, system, messages):
    """The full conversation (system + user + tool calls + tool results + final answer) - the
    publishable audit trail that nothing was hand-picked. Carries the isolation tier the tool code
    ran under."""
    return {"backend": "anthropic", "model": model, "isolation_tier": _detect_tier(),
            "system": system, "messages": messages}


def _parse_verdict(text):
    """Extract the trailing JSON verdict from the agent's final message."""
    i, j = text.rfind("{"), text.rfind("}")
    if i != -1 and j > i:
        try:
            d = json.loads(text[i:j + 1])
            v = str(d.get("verdict", "abstain")).lower()
            if v not in ("honest", "flawed", "abstain"):
                v = "abstain"
            return {"verdict": v, "recomputed": d.get("recomputed"), "why": d.get("why", "")}
        except ValueError:
            pass
    return {"verdict": "abstain", "recomputed": None, "why": "unparseable"}


# ---- driver ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="deterministic offline backend (no API key)")
    ap.add_argument("--k", type=int, default=5, help="reruns per case (variance / instability)")
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--limit", type=int, default=0, help="cap cases (for a quick check)")
    a = ap.parse_args()
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    if a.limit:
        manifest = manifest[:a.limit]
    if not a.mock and "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("error: set ANTHROPIC_API_KEY, or pass --mock for the offline plumbing check")

    tier = _detect_tier()
    if tier == "host-not-isolated":
        print("WARNING: no verified network-off sandbox on this host (tier=host-not-isolated) - agent "
              "runs will NOT be counted (untrusted code is never run unsandboxed).", file=sys.stderr)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    tdir = os.path.join(HERE, "results", "agent_transcripts")
    os.makedirs(tdir, exist_ok=True)
    out, excluded = [], []
    for m in manifest:
        art = _ensure_data(m)
        t0 = time.time()
        reruns, usd_total, last = [], 0.0, None
        for k in range(a.k):
            if a.mock:
                res = _mock_agent(m, art); usd = 0.0
                tr = {"backend": "mock", "isolation_tier": tier, "system": SYSTEM,
                      "user": {"metric": m["metric"], "claim": m.get("claim_text") or m.get("claim"),
                               "file": os.path.basename(art) if art else None}, "result": res}
            else:
                res, usd, tr = _anthropic_agent(m, art, a.model)
            reruns.append(res["verdict"]); usd_total += usd; last = res
            # persist the full transcript per run (the publishable audit trail; every record has a tier)
            json.dump(tr, open(os.path.join(tdir, "%s_run%d.json" % (m["id"], k)), "w"), indent=2)
        ms = int((time.time() - t0) * 1000)
        # prediction = majority vote over the K reruns (ties -> abstain, the safe answer)
        counts = {v: reruns.count(v) for v in set(reruns)}
        top = max(counts.values())
        winners = [v for v, c in counts.items() if c == top]
        pred = winners[0] if len(winners) == 1 else "abstain"
        rec = {"id": m["id"], "metric": m["metric"], "claim": m["claim"], "label": m["label"],
               "track": m.get("track"), "family": m.get("family"), "tier": m.get("tier"),
               "validity_family": m.get("validity_family"),
               "prediction": pred, "recomputed": (last or {}).get("recomputed"),
               "reruns": reruns, "unstable": len(set(reruns)) > 1,
               "ms": ms, "usd": round(usd_total, 4), "isolation_tier": tier}
        # a run that could not be network-off-isolated is EXCLUDED from the scored result, never counted
        (excluded if tier == "host-not-isolated" else out).append(rec)
        print("%-22s pred=%-7s reruns=%s%s" % (m["id"], pred, reruns,
              "  UNSTABLE" if len(set(reruns)) > 1 else ""))

    dest = os.path.join(HERE, "results", "agent.json")
    json.dump(out, open(dest, "w"), indent=2)
    if excluded:
        json.dump(excluded, open(os.path.join(HERE, "results", "agent_excluded.json"), "w"), indent=2)
    inst = sum(1 for r in out if r["unstable"]) / len(out) if out else 0.0
    usd = sum(r["usd"] for r in out)
    print("\nwrote %s  (%d counted cases @ tier=%s, instability %.0f%%, $%.2f%s)"
          % (dest, len(out), tier, inst * 100, usd, ", MOCK" if a.mock else ""))
    if excluded:
        print("EXCLUDED %d host-not-isolated case(s) -> results/agent_excluded.json (not counted)"
              % len(excluded))
    print("wrote %d transcripts to %s" % (len(manifest) * a.k, tdir))
    print("now run: python3 benchmark/score.py   (it picks up results/agent.json automatically)")


if __name__ == "__main__":
    main()
