"""calma.otel_eval - emit a finished Calma verdict as a standard OpenTelemetry GenAI *evaluation result*,
so any agent-observability backend (Braintrust / LangSmith / Langfuse / Phoenix) ingests Calma as a
drop-in DETERMINISTIC eval source with zero custom integration. This is the OTel-eval distribution wedge
(master roadmap §4 / P2-M7a).

FIREWALL (same discipline as edges/): this module CONSUMES a finished verdict dict and never participates
in deriving one. The deterministic core never imports it; it imports only `verdict` (a pure-stdlib leaf)
to key the enum->label map off the single source of truth. PURE STDLIB - urllib + json + hashlib only, so
the self-emit path is zero-dependency (the "no deps" SDK). The optional OpenTelemetry-SDK integration lives
in the pip facade (`calma.otel`), never here.

REDACTION BY CONSTRUCTION: map_verdict() copies a strict WHITELIST of fields (verdict, metric, claimed,
recomputed, gap, budget, isolation, determinism, version, run_url, bundle hash, confidence, reason). No raw
data, no input bundle, no verdict_inputs dump ever reaches a span - identical to the registry whitelist.

Semantic conventions (pinned to open-telemetry/semantic-conventions-genai, all `Development` status):
  event/span name  = "gen_ai.evaluation.result"
  gen_ai.operation.name = "evaluation" ; gen_ai.system = "calma"
  gen_ai.evaluation.name = "calma.<metric>"           (low-cardinality, stable per metric)
  gen_ai.evaluation.score.value = the recomputed number (double) - the determinism payoff
  gen_ai.evaluation.score.label = pass|fail            (OMITTED for CAN'T-CONFIRM: never assert pass/fail)
  gen_ai.evaluation.outcome     = pass|fail|allow|block (the categorical decision)
  gen_ai.evaluation.explanation = the engine's verdict_with_reason() line

Verdict -> (score.label, outcome) is CANONICAL-DECISIONS §3 (extends 03 §4.2 with FLAG_FOR_DECLARATION).

Run standalone:  python3 otel_eval.py [--endpoint URL] [--dual braintrust,langsmith] < ledger.json
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402 - pure-stdlib leaf; keys the enum->label map to the one source of truth

_SCOPE_NAME = "calma-otel"
_EVAL_NAME = "gen_ai.evaluation.result"

# Verdict enum -> (score.label, outcome). label=None => OMIT score.label (CAN'T-CONFIRM never asserts a
# pass/fail). INVALIDATED and FLAG_FOR_DECLARATION both map outcome=block: the number reproduces but the
# RESULT is invalid / carries undeclared invalidating structure -> "block" is the honest action signal.
# Keyed off the engine constants (single source of truth) + the two rollup/display literals.
VERDICT_MAP = {
    V.CONFIRMED: ("pass", "pass"),
    V.CAVEATS: ("pass", "pass"),
    V.REFUTED: ("fail", "fail"),
    V.INVALIDATED: ("fail", "block"),
    V.FLAG_FOR_DECLARATION: ("fail", "block"),
    "MIXED": ("fail", "fail"),
    V.INCONCLUSIVE: (None, "allow"),
    "CAN'T-CONFIRM": (None, "allow"),   # the display name of INCONCLUSIVE, accepted as an alias
}

# OTLP span status codes: 0=UNSET, 1=OK, 2=ERROR. A catch (fail/block) is surfaced as ERROR; a pass as OK;
# a can't-confirm (allow) stays UNSET (honest silence, not a failure).
_STATUS = {"pass": 1, "fail": 2, "block": 2, "allow": 0}


def _headline_claim(led):
    claims = led.get("claims") or []
    if not claims:
        return {}
    return next((c for c in claims if c.get("headline")), claims[0])


def _extract(result):
    """Normalize a ledger (repo_verdict + claims) OR a flat run-result (verdict + metric + ...) into the
    fields the eval span needs. Headline-claim driven for a ledger. Whitelist only - never copies raw data."""
    if "repo_verdict" in result or "claims" in result:          # a ledger
        c = _headline_claim(result)
        vi = c.get("verdict_inputs") or {}
        scope = result.get("scope") or {}
        reason = c.get("reason")
        if not reason and c.get("verdict_inputs") is not None:
            # spec-true explanation = verdict_with_reason()'s single most-limiting line
            reason = V.verdict_with_reason(vi)[1]
        return {
            "verdict": result.get("repo_verdict"),
            "metric": c.get("metric"),
            "claimed": c.get("claimed_value"),
            "recomputed": c.get("recomputed_value"),
            "reason": reason,
            "confidence": c.get("headline_confidence"),
            "gap": vi.get("gap"),
            "effective_budget": vi.get("effective_budget"),
            "isolation_tier": vi.get("isolation_tier") or scope.get("isolation_tier"),
            "determinism_mode": vi.get("determinism_mode") or scope.get("determinism_mode"),
            "engine_version": result.get("engine_version"),
            "run_url": result.get("run_url"),
            "bundle_sha256": result.get("bundle_sha256") or result.get("manifest_ref"),
            "run_id": result.get("run_id") or result.get("verification_id"),
        }
    # a flat run-result dict (the shape calma.verify() returns per claim / the control-plane row)
    return {
        "verdict": result.get("verdict"),
        "metric": result.get("metric"),
        "claimed": result.get("claimed", result.get("claimed_value")),
        "recomputed": result.get("recomputed", result.get("recomputed_value")),
        "reason": result.get("reason"),
        "confidence": result.get("confidence", result.get("headline_confidence")),
        "gap": result.get("gap"),
        "effective_budget": result.get("effective_budget"),
        "isolation_tier": result.get("isolation_tier"),
        "determinism_mode": result.get("determinism_mode"),
        "engine_version": result.get("engine_version"),
        "run_url": result.get("run_url"),
        "bundle_sha256": result.get("bundle_sha256") or result.get("manifest_ref"),
        "run_id": result.get("run_id") or result.get("verification_id"),
    }


def map_verdict(result, *, run_url=None, engine_version=None):
    """A finished verdict (ledger or run-result) -> the flat OTel GenAI-eval attribute dict. Redaction by
    construction: only the whitelist below is ever emitted; no raw data, no verdict_inputs vector."""
    f = _extract(result)
    label, outcome = VERDICT_MAP.get(f["verdict"], (None, "allow"))   # unknown verdict -> never asserts pass/fail
    attrs = {
        "gen_ai.operation.name": "evaluation",
        "gen_ai.system": "calma",
        "gen_ai.evaluation.name": "calma.%s" % (f["metric"] or "result"),
        "gen_ai.evaluation.outcome": outcome,
        "calma.verdict": f["verdict"],
        "calma.evaluator": "calma",
    }
    if f["recomputed"] is not None:
        attrs["gen_ai.evaluation.score.value"] = _num(f["recomputed"])
    if label is not None:
        attrs["gen_ai.evaluation.score.label"] = label
    if f["reason"]:
        attrs["gen_ai.evaluation.explanation"] = f["reason"]
    # calma-native differentiators (the determinism payoff); every value optional, omitted when absent.
    native = [
        ("calma.confidence", _num(f["confidence"]) if f["confidence"] is not None else None),
        ("calma.claimed", _num(f["claimed"]) if f["claimed"] is not None else None),
        ("calma.recomputed", _num(f["recomputed"]) if f["recomputed"] is not None else None),
        ("calma.gap", _num(f["gap"]) if f["gap"] is not None else None),
        ("calma.effective_budget", _num(f["effective_budget"]) if f["effective_budget"] is not None else None),
        ("calma.isolation_tier", f["isolation_tier"]),
        ("calma.determinism_mode", f["determinism_mode"]),
        ("calma.engine_version", engine_version or f["engine_version"]),
        ("calma.run_url", run_url or f["run_url"]),
        ("calma.bundle_sha256", f["bundle_sha256"]),
    ]
    for k, v in native:
        if v is not None:
            attrs[k] = v
    return attrs


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


# --- dual-emit: mirror the verdict into a backend's NATIVE namespace on the same span, so ingestion works
# even where a backend hasn't adopted the GenAI-eval event yet (03 §4.1). Backends that read gen_ai.* natively
# (Langfuse, Phoenix) need no mirror; Braintrust + LangSmith do. Nested values are JSON-encoded (OTLP scalars).

def dual_emit_attrs(attrs, backends):
    out = dict(attrs)
    name = attrs.get("gen_ai.evaluation.name", "calma.result")
    outcome = attrs.get("gen_ai.evaluation.outcome", "allow")
    score01 = 1.0 if outcome == "pass" else (0.0 if outcome in ("fail", "block") else None)
    meta = {k[len("calma."):]: attrs[k] for k in attrs if k.startswith("calma.")}
    for b in backends:
        b = b.strip().lower()
        if b == "braintrust":
            # Braintrust has no native GenAI-eval reader -> emit its score namespace on the same span.
            out["braintrust.span_attributes"] = json.dumps({"type": "score", "name": name})
            if score01 is not None:
                out["braintrust.scores"] = json.dumps({"calma": score01})
            out["braintrust.metadata"] = json.dumps(meta)
            if attrs.get("calma.claimed") is not None:
                out["braintrust.input"] = json.dumps({"claimed": attrs.get("calma.claimed")})
            if attrs.get("gen_ai.evaluation.score.value") is not None:
                out["braintrust.output"] = json.dumps({"recomputed": attrs["gen_ai.evaluation.score.value"]})
        elif b == "langsmith":
            # LangSmith threads on its own discriminators; the canonical gen_ai.* ride along for forward-compat.
            out["langsmith.span.kind"] = "EVALUATOR"
            out["langsmith.metadata.calma_verdict"] = attrs.get("calma.verdict")
        elif b in ("langfuse", "phoenix"):
            pass  # both read gen_ai.* natively - the canonical mapping is sufficient, no mirror needed.
    return out


# --- OTLP/HTTP JSON encoding (the zero-dep transport). trace_id/span_id are HEX strings per the OTLP/JSON
# spec's deliberate exception to protobuf-JSON base64; every other bytes field is unused here.

def _anyvalue(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    return {"stringValue": str(v)}


def _kv(d):
    return [{"key": k, "value": _anyvalue(v)} for k, v in d.items()]


def _ids(seed):
    """Deterministic (trace_id, span_id) from a stable seed - so a redelivery of the SAME verdict overwrites
    rather than duplicates (CANONICAL: the OTel emit is keyed by run_id). 32-hex trace, 16-hex span."""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return h[:32], h[32:48]


def build_otlp_traces(attrs, *, name=_EVAL_NAME, trace_id, span_id, start_unix_nano=0, end_unix_nano=0,
                      evaluated_trace_id=None, evaluated_span_id=None, resource_attrs=None,
                      scope_name=_SCOPE_NAME, scope_version=None):
    """Build the OTLP/HTTP JSON traces payload: a standalone `gen_ai.evaluation.result` span carrying the
    eval attributes, optionally LINKED to the evaluated agent span ({trace_id, span_id}). Pure: the caller
    supplies ids + timestamps (so it is deterministic and unit-testable)."""
    outcome = attrs.get("gen_ai.evaluation.outcome", "allow")
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,   # SPAN_KIND_INTERNAL
        "startTimeUnixNano": str(start_unix_nano),
        "endTimeUnixNano": str(end_unix_nano),
        "attributes": _kv(attrs),
        "status": {"code": _STATUS.get(outcome, 0)},
    }
    if evaluated_trace_id and evaluated_span_id:
        span["links"] = [{"traceId": evaluated_trace_id, "spanId": evaluated_span_id}]
    return {
        "resourceSpans": [{
            "resource": {"attributes": _kv(resource_attrs or {"service.name": "calma"})},
            "scopeSpans": [{
                "scope": {"name": scope_name, "version": scope_version or ""},
                "spans": [span],
            }],
        }],
    }


def _parse_otlp_headers(s):
    """Parse the standard OTEL_EXPORTER_OTLP_HEADERS form: 'k1=v1,k2=v2'."""
    out = {}
    for part in (s or "").split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def emit_otlp(payload, *, endpoint=None, headers=None, timeout=5.0):
    """POST an OTLP/HTTP JSON payload to <endpoint>/v1/traces. Honors OTEL_EXPORTER_OTLP_ENDPOINT /
    OTEL_EXPORTER_OTLP_HEADERS so the user points it at THEIR backend and Calma rides their pipeline.
    Returns (status_code, body) or None when nothing is configured (an honest no-op, not an error)."""
    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    url = endpoint.rstrip("/")
    if not url.endswith("/v1/traces"):
        url += "/v1/traces"
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(_parse_otlp_headers(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")))
    if headers:
        hdrs.update(headers)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:        # nosec - user-configured endpoint
        return getattr(resp, "status", resp.getcode()), resp.read().decode("utf-8", "replace")


def emit_verdict(result, *, endpoint=None, headers=None, dual_emit=(), evaluated=None, run_url=None,
                 engine_version=None, start_unix_nano=None, end_unix_nano=None, dry_run=False):
    """The one-call self-emit: map a finished verdict -> OTel eval span -> OTLP POST. `dual_emit` is an
    iterable of backend names ('braintrust','langsmith'). `evaluated` = {'trace_id','span_id'} to LINK this
    eval to the agent operation it scored. dry_run builds the payload without POSTing (CI / tests).
    Returns {payload, emitted, status, trace_id, span_id}."""
    attrs = map_verdict(result, run_url=run_url, engine_version=engine_version)
    if dual_emit:
        attrs = dual_emit_attrs(attrs, list(dual_emit))
    seed = _seed(result, attrs)
    trace_id, span_id = _ids(seed)
    if start_unix_nano is None:
        start_unix_nano = 0 if dry_run else _now_ns()
    if end_unix_nano is None:
        end_unix_nano = start_unix_nano
    ev_tid = ev_sid = None
    if evaluated:
        ev_tid, ev_sid = evaluated.get("trace_id"), evaluated.get("span_id")
    payload = build_otlp_traces(attrs, trace_id=trace_id, span_id=span_id,
                                start_unix_nano=start_unix_nano, end_unix_nano=end_unix_nano,
                                evaluated_trace_id=ev_tid, evaluated_span_id=ev_sid,
                                scope_version=engine_version or "")
    status = None if dry_run else emit_otlp(payload, endpoint=endpoint, headers=headers)
    return {"payload": payload, "emitted": status is not None, "status": status,
            "trace_id": trace_id, "span_id": span_id}


def _seed(result, attrs):
    """A stable idempotency seed for this verdict: the run/verification id when present, else a content hash
    of the canonical attributes (sorted) - so the SAME verdict always maps to the SAME span id."""
    f = _extract(result)
    if f.get("run_id"):
        return "calma:run:%s" % f["run_id"]
    if attrs.get("calma.bundle_sha256"):
        return "calma:bundle:%s" % attrs["calma.bundle_sha256"]
    return "calma:attrs:" + json.dumps(attrs, sort_keys=True, default=str)


def _now_ns():
    import time
    return time.time_ns()


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Emit a Calma verdict as an OTel GenAI evaluation result.")
    ap.add_argument("--endpoint", help="OTLP/HTTP base (default: $OTEL_EXPORTER_OTLP_ENDPOINT)")
    ap.add_argument("--dual", default="", help="comma-separated backends to dual-emit (braintrust,langsmith)")
    ap.add_argument("--run-url", default=None)
    ap.add_argument("--engine-version", default=None)
    ap.add_argument("--dry-run", action="store_true", help="build + print the payload, do not POST")
    ap.add_argument("ledger", nargs="?", help="ledger.json path (default: stdin)")
    a = ap.parse_args(argv)
    raw = open(a.ledger).read() if a.ledger else sys.stdin.read()
    result = json.loads(raw)
    dual = [b for b in a.dual.split(",") if b.strip()]
    res = emit_verdict(result, endpoint=a.endpoint, dual_emit=dual, run_url=a.run_url,
                       engine_version=a.engine_version, dry_run=a.dry_run or not (
                           a.endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")))
    print(json.dumps(res["payload"], indent=2))
    if res["emitted"]:
        sys.stderr.write("emitted -> %s (status %s)\n" % (
            a.endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"), res["status"][0]))
    else:
        sys.stderr.write("dry-run (no OTLP endpoint configured) - payload printed above\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
