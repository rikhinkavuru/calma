"""Tests for otel_eval.py - the OTel-eval distribution wedge (P2-M7a). Pure stdlib (no opentelemetry, no
pytest). Covers the full verdict->mapping table (incl. FLAG_FOR_DECLARATION), redaction-by-construction, the
OTLP/HTTP JSON shape, deterministic idempotent ids, dual-emit, and a HERMETIC ingest test that spins up a
stdlib http.server as a local OTLP collector stand-in and asserts the captured POST body.
Run: python3 test_otel_eval.py
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import otel_eval as OE  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _ledger(repo_verdict, *, metric="total_return", claimed=146.9, recomputed=-0.32, vi=None):
    return {
        "repo_verdict": repo_verdict,
        "engine_version": "0.12.0",
        "run_id": "run-%s" % repo_verdict,
        "scope": {"isolation_tier": "e2b-firecracker", "determinism_mode": "controlled-to-bit"},
        "claims": [{
            "id": "c1", "headline": True, "verdict": repo_verdict, "metric": metric,
            "claimed_value": claimed, "recomputed_value": recomputed, "headline_confidence": 0.81,
            "verdict_inputs": vi or {"gap": 147.0, "effective_budget": 0.01,
                                     "isolation_tier": "e2b-firecracker",
                                     "determinism_mode": "controlled-to-bit"},
        }],
        "findings": [],
    }


# ---- the full verdict -> (score.label, outcome) table (CANONICAL §3, incl. FLAG_FOR_DECLARATION) ----
TABLE = {
    V.CONFIRMED: ("pass", "pass"),
    V.CAVEATS: ("pass", "pass"),
    V.REFUTED: ("fail", "fail"),
    V.INVALIDATED: ("fail", "block"),
    V.FLAG_FOR_DECLARATION: ("fail", "block"),
    "MIXED": ("fail", "fail"),
    V.INCONCLUSIVE: (None, "allow"),
}
for verdict_, (want_label, want_outcome) in TABLE.items():
    attrs = OE.map_verdict(_ledger(verdict_))
    expect(attrs["gen_ai.evaluation.outcome"] == want_outcome,
           "%s -> outcome %s (got %s)" % (verdict_, want_outcome, attrs.get("gen_ai.evaluation.outcome")))
    if want_label is None:
        expect("gen_ai.evaluation.score.label" not in attrs,
               "%s OMITS score.label (never asserts pass/fail)" % verdict_)
    else:
        expect(attrs.get("gen_ai.evaluation.score.label") == want_label,
               "%s -> score.label %s" % (verdict_, want_label))

# the two block-outcome catches are exactly INVALIDATED + FLAG_FOR_DECLARATION
_blocks = {v for v, (_, o) in TABLE.items() if o == "block"}
expect(_blocks == {V.INVALIDATED, V.FLAG_FOR_DECLARATION}, "block outcome == {INVALIDATED, FLAG}")

# ---- the required GenAI attributes + the calma-native differentiators are present ----
a = OE.map_verdict(_ledger(V.REFUTED), run_url="https://app.calma.dev/runs/x", engine_version="0.12.0")
expect(a["gen_ai.operation.name"] == "evaluation", "operation.name=evaluation")
expect(a["gen_ai.system"] == "calma", "system=calma")
expect(a["gen_ai.evaluation.name"] == "calma.total_return", "name namespaced calma.<metric>")
expect(a["gen_ai.evaluation.score.value"] == -0.32, "score.value == the recomputed number")
expect(a.get("gen_ai.evaluation.explanation"), "explanation present (verdict_with_reason line)")
expect(a["calma.verdict"] == V.REFUTED and a["calma.run_url"].endswith("/x"), "calma-native attrs present")
expect(a["calma.isolation_tier"] == "e2b-firecracker", "isolation tier carried")

# ---- REDACTION BY CONSTRUCTION: only the whitelist leaves; no raw data, no verdict_inputs vector ----
led = _ledger(V.REFUTED)
led["claims"][0]["verdict_inputs"]["SECRET_RAW_ROWS"] = [[1, 2, 3], [4, 5, 6]]   # must NOT escape
led["raw_input_bundle"] = "s3://bucket/secret.csv"
a2 = OE.map_verdict(led)
blob = json.dumps(a2)
expect("SECRET_RAW_ROWS" not in blob and "secret.csv" not in blob, "no raw data / bundle leaks into a span")
allowed_prefixes = ("gen_ai.", "calma.")
expect(all(k.startswith(allowed_prefixes) for k in a2), "every attribute key is gen_ai.* or calma.*")

# ---- OTLP/HTTP JSON shape ----
res = OE.emit_verdict(_ledger(V.REFUTED), dry_run=True, run_url="https://app.calma.dev/runs/x")
p = res["payload"]
span = p["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
expect(span["name"] == "gen_ai.evaluation.result", "span name = gen_ai.evaluation.result")
expect(p["resourceSpans"][0]["scopeSpans"][0]["scope"]["name"] == "calma-otel", "scope = calma-otel")
expect(span["status"]["code"] == 2, "REFUTED span status = ERROR(2)")
expect(len(span["traceId"]) == 32 and len(span["spanId"]) == 16, "hex trace(32)/span(16) ids")
# attribute KV encoding: doubles as doubleValue, strings as stringValue
kv = {x["key"]: x["value"] for x in span["attributes"]}
expect("doubleValue" in kv["gen_ai.evaluation.score.value"], "score.value encoded as doubleValue")
expect("stringValue" in kv["gen_ai.evaluation.outcome"], "outcome encoded as stringValue")

# a clean CONFIRMED is OK(1) status; CAN'T-CONFIRM is UNSET(0)
expect(OE.emit_verdict(_ledger(V.CONFIRMED, recomputed=2.0), dry_run=True)["payload"]
       ["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["status"]["code"] == 1, "CONFIRMED -> OK(1)")
expect(OE.emit_verdict(_ledger(V.INCONCLUSIVE), dry_run=True)["payload"]
       ["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["status"]["code"] == 0, "CAN'T-CONFIRM -> UNSET(0)")

# ---- deterministic, idempotent ids: same verdict -> same span id (redelivery overwrites, not duplicates) ----
r1 = OE.emit_verdict(_ledger(V.REFUTED), dry_run=True)
r2 = OE.emit_verdict(_ledger(V.REFUTED), dry_run=True)
expect(r1["span_id"] == r2["span_id"] and r1["trace_id"] == r2["trace_id"], "same verdict -> same ids")
expect(OE.emit_verdict(_ledger(V.CONFIRMED, recomputed=2.0), dry_run=True)["span_id"] != r1["span_id"],
       "different run -> different ids")

# ---- link to the evaluated agent span ----
linked = OE.emit_verdict(_ledger(V.REFUTED), dry_run=True,
                         evaluated={"trace_id": "a" * 32, "span_id": "b" * 16})
lspan = linked["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
expect(lspan.get("links") and lspan["links"][0]["spanId"] == "b" * 16, "eval span LINKS to the evaluated span")

# ---- dual-emit: Braintrust score namespace (0/1 from outcome) on the same span ----
d = OE.map_verdict(_ledger(V.REFUTED))
d = OE.dual_emit_attrs(d, ["braintrust", "langsmith"])
expect(json.loads(d["braintrust.scores"]) == {"calma": 0.0}, "braintrust score 0.0 for a fail")
expect(d["langsmith.span.kind"] == "EVALUATOR", "langsmith discriminator set")
dc = OE.dual_emit_attrs(OE.map_verdict(_ledger(V.CONFIRMED, recomputed=2.0)), ["braintrust"])
expect(json.loads(dc["braintrust.scores"]) == {"calma": 1.0}, "braintrust score 1.0 for a pass")

# ---- HERMETIC INGEST: a stdlib http.server stands in for an OTLP collector; assert the captured POST ----
_captured = {}


class _Collector(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _captured["path"] = self.path
        _captured["ctype"] = self.headers.get("Content-Type")
        _captured["auth"] = self.headers.get("Authorization")
        _captured["body"] = json.loads(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"partialSuccess":{}}')

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), _Collector)
threading.Thread(target=srv.handle_request, daemon=True).start()
endpoint = "http://127.0.0.1:%d" % srv.server_address[1]
out = OE.emit_verdict(_ledger(V.REFUTED), endpoint=endpoint, headers={"Authorization": "Bearer k"},
                      run_url="https://app.calma.dev/runs/x")
srv.server_close()
expect(out["emitted"] and out["status"][0] == 200, "OTLP POST accepted (200)")
expect(_captured.get("path") == "/v1/traces", "POSTed to /v1/traces")
expect(_captured.get("ctype") == "application/json", "content-type application/json")
expect(_captured.get("auth") == "Bearer k", "custom header forwarded")
cap_span = _captured["body"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
cap_kv = {x["key"]: x["value"] for x in cap_span["attributes"]}
expect(cap_kv["calma.verdict"]["stringValue"] == "REFUTED", "captured body carries calma.verdict=REFUTED")
expect(cap_kv["gen_ai.evaluation.outcome"]["stringValue"] == "fail", "captured outcome=fail")

# ---- per-backend adapter recipes (§4.4): copy-paste OTLP config for the 4 backends ----
expect(set(OE.ADAPTERS) == {"braintrust", "langsmith", "langfuse", "phoenix"}, "the 4 backend adapters exist")
bt = OE.adapter_config("braintrust")
expect(bt["endpoint"] == "https://api.braintrust.dev/otel" and bt["dual_emit"] == ["braintrust"],
       "braintrust adapter: endpoint + braintrust dual-emit (no native gen_ai reader)")
expect("OTEL_EXPORTER_OTLP_ENDPOINT" in bt["otel_env"] and "Bearer ${BRAINTRUST_API_KEY}" in bt["otel_env"]["OTEL_EXPORTER_OTLP_HEADERS"],
       "adapter_config yields a ready-to-paste OTEL_EXPORTER_OTLP_* block with ${ENV} placeholders")
lf = OE.adapter_config("LangFuse")                       # case-insensitive
expect(lf["dual_emit"] == [] and lf["reads_gen_ai"] is True, "langfuse reads gen_ai.* natively -> no dual-emit")
expect(all("dual_emit" in OE.adapter_config(b) and OE.adapter_config(b)["env"] for b in OE.ADAPTERS),
       "every adapter names its dual-emit + the env vars to set")
try:
    OE.adapter_config("nope")
    expect(False, "adapter_config raises on an unknown backend")
except KeyError:
    expect(True, "adapter_config raises on an unknown backend")

print("otel_eval.py: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
