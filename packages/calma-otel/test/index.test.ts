import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import {
  mapVerdict, buildOtlpTraces, dualEmitAttrs, ids, emitVerdict, CalmaSpanProcessor,
  VERDICT_MAP, EVAL_NAME, ADAPTERS, adapterConfig, type VerdictResult,
} from "../src/index.ts";

function ledger(repoVerdict: string, over: Partial<Record<string, unknown>> = {}): VerdictResult {
  return {
    repo_verdict: repoVerdict as VerdictResult["repo_verdict"],
    engine_version: "0.12.0",
    run_id: `run-${repoVerdict}`,
    scope: { isolation_tier: "e2b-firecracker", determinism_mode: "controlled-to-bit" },
    claims: [{
      id: "c1", headline: true, verdict: repoVerdict, metric: "total_return",
      claimed_value: 146.9, recomputed_value: -0.32, headline_confidence: 0.81,
      verdict_inputs: { gap: 147.0, effective_budget: 0.01, isolation_tier: "e2b-firecracker", determinism_mode: "controlled-to-bit" },
      ...over,
    }],
    findings: [],
  } as unknown as VerdictResult;
}

const TABLE: Record<string, [string | null, string]> = {
  "CONFIRMED": ["pass", "pass"],
  "CONFIRMED-WITH-CAVEATS": ["pass", "pass"],
  "REFUTED": ["fail", "fail"],
  "INVALIDATED": ["fail", "block"],
  "FLAG_FOR_DECLARATION": ["fail", "block"],
  "MIXED": ["fail", "fail"],
  "INCONCLUSIVE": [null, "allow"],
};

test("verdict -> (score.label, outcome) table incl. FLAG_FOR_DECLARATION (CANONICAL §3)", () => {
  for (const [verdict, [wantLabel, wantOutcome]] of Object.entries(TABLE)) {
    const a = mapVerdict(ledger(verdict));
    assert.equal(a["gen_ai.evaluation.outcome"], wantOutcome, `${verdict} outcome`);
    if (wantLabel === null) assert.ok(!("gen_ai.evaluation.score.label" in a), `${verdict} omits score.label`);
    else assert.equal(a["gen_ai.evaluation.score.label"], wantLabel, `${verdict} label`);
  }
  // the two block-outcome catches are exactly INVALIDATED + FLAG_FOR_DECLARATION
  const blocks = Object.entries(VERDICT_MAP).filter(([, [, o]]) => o === "block").map(([v]) => v).sort();
  assert.deepEqual(blocks, ["FLAG_FOR_DECLARATION", "INVALIDATED"]);
});

test("required GenAI attrs + the calma-native differentiators are present", () => {
  const a = mapVerdict(ledger("REFUTED"), { runUrl: "https://app.calma.dev/runs/x", engineVersion: "0.12.0" });
  assert.equal(a["gen_ai.operation.name"], "evaluation");
  assert.equal(a["gen_ai.system"], "calma");
  assert.equal(a["gen_ai.evaluation.name"], "calma.total_return");
  assert.equal(a["gen_ai.evaluation.score.value"], -0.32);
  assert.equal(a["calma.verdict"], "REFUTED");
  assert.ok(String(a["calma.run_url"]).endsWith("/x"));
  assert.equal(a["calma.isolation_tier"], "e2b-firecracker");
});

test("REDACTION: only gen_ai.* / calma.* keys leave; no raw data or verdict_inputs vector", () => {
  const led = ledger("REFUTED", { verdict_inputs: { gap: 147, SECRET_RAW_ROWS: [[1, 2], [3, 4]] } });
  (led as Record<string, unknown>).raw_input_bundle = "s3://bucket/secret.csv";
  const a = mapVerdict(led);
  const blob = JSON.stringify(a);
  assert.ok(!blob.includes("SECRET_RAW_ROWS") && !blob.includes("secret.csv"), "no raw data leaks");
  assert.ok(Object.keys(a).every((k) => k.startsWith("gen_ai.") || k.startsWith("calma.")), "whitelist only");
});

test("OTLP/HTTP JSON shape + hex ids + status codes", () => {
  const r = mapVerdict(ledger("REFUTED"));
  const { traceId, spanId } = ids("calma:run:run-REFUTED");
  const p = buildOtlpTraces(r, { traceId, spanId }) as any;
  const span = p.resourceSpans[0].scopeSpans[0].spans[0];
  assert.equal(span.name, EVAL_NAME);
  assert.equal(p.resourceSpans[0].scopeSpans[0].scope.name, "@calma/otel");
  assert.equal(span.status.code, 2, "REFUTED -> ERROR(2)");
  assert.equal(traceId.length, 32);
  assert.equal(spanId.length, 16);
  const kv = Object.fromEntries(span.attributes.map((x: any) => [x.key, x.value]));
  assert.ok("doubleValue" in kv["gen_ai.evaluation.score.value"], "score.value as doubleValue");
  assert.ok("stringValue" in kv["gen_ai.evaluation.outcome"], "outcome as stringValue");
  // CONFIRMED -> OK(1), CAN'T-CONFIRM -> UNSET(0)
  const ok = buildOtlpTraces(mapVerdict(ledger("CONFIRMED")), { traceId, spanId }) as any;
  assert.equal(ok.resourceSpans[0].scopeSpans[0].spans[0].status.code, 1);
  const unset = buildOtlpTraces(mapVerdict(ledger("INCONCLUSIVE")), { traceId, spanId }) as any;
  assert.equal(unset.resourceSpans[0].scopeSpans[0].spans[0].status.code, 0);
});

test("deterministic, idempotent ids: same verdict -> same span id", async () => {
  const r1 = await emitVerdict(ledger("REFUTED"), { dryRun: true });
  const r2 = await emitVerdict(ledger("REFUTED"), { dryRun: true });
  assert.equal(r1.spanId, r2.spanId);
  assert.equal(r1.traceId, r2.traceId);
  const r3 = await emitVerdict(ledger("CONFIRMED"), { dryRun: true });
  assert.notEqual(r3.spanId, r1.spanId);
});

test("eval span LINKS to the evaluated agent span", async () => {
  const r = await emitVerdict(ledger("REFUTED"), { dryRun: true, evaluated: { traceId: "a".repeat(32), spanId: "b".repeat(16) } });
  const span = (r.payload as any).resourceSpans[0].scopeSpans[0].spans[0];
  assert.equal(span.links[0].spanId, "b".repeat(16));
});

test("dual-emit: Braintrust score 0/1 from the outcome", () => {
  const fail = dualEmitAttrs(mapVerdict(ledger("REFUTED")), ["braintrust", "langsmith"]);
  assert.deepEqual(JSON.parse(String(fail["braintrust.scores"])), { calma: 0.0 });
  assert.equal(fail["langsmith.span.kind"], "EVALUATOR");
  const pass = dualEmitAttrs(mapVerdict(ledger("CONFIRMED")), ["braintrust"]);
  assert.deepEqual(JSON.parse(String(pass["braintrust.scores"])), { calma: 1.0 });
});

test("CalmaSpanProcessor event mode records a span-event on a live span", async () => {
  let captured: { name?: string; attrs?: Record<string, unknown> } = {};
  const fakeSpan = { addEvent: (name: string, attrs: Record<string, unknown>) => { captured = { name, attrs }; } };
  const out = await new CalmaSpanProcessor().emit(ledger("FLAG_FOR_DECLARATION"), { span: fakeSpan, mode: "event" });
  assert.equal((out as any).mode, "event");
  assert.equal(captured.name, EVAL_NAME);
  assert.equal(captured.attrs!["gen_ai.evaluation.outcome"], "block");
});

test("per-backend adapter recipes (§4.4): copy-paste OTLP config for the 4 backends", () => {
  assert.deepEqual(Object.keys(ADAPTERS).sort(), ["braintrust", "langfuse", "langsmith", "phoenix"]);
  const bt = adapterConfig("BrainTrust"); // case-insensitive
  assert.equal(bt.endpoint, "https://api.braintrust.dev/otel");
  assert.deepEqual(bt.dualEmit, ["braintrust"]);
  assert.ok(bt.otelEnv.OTEL_EXPORTER_OTLP_HEADERS.includes("Bearer ${BRAINTRUST_API_KEY}"));
  const lf = adapterConfig("langfuse");
  assert.deepEqual(lf.dualEmit, []);
  assert.equal(lf.readsGenAi, true);
  assert.throws(() => adapterConfig("nope"), /unknown backend/);
});

test("HERMETIC INGEST: a node http server stands in for an OTLP collector", async () => {
  const cap: { path?: string; ctype?: string | string[]; auth?: string | string[]; body?: any } = {};
  const srv = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      cap.path = req.url;
      cap.ctype = req.headers["content-type"];
      cap.auth = req.headers["authorization"];
      cap.body = JSON.parse(Buffer.concat(chunks).toString());
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end('{"partialSuccess":{}}');
    });
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
  const port = (srv.address() as { port: number }).port;
  const out = await emitVerdict(ledger("REFUTED"), {
    endpoint: `http://127.0.0.1:${port}`, headers: { Authorization: "Bearer k" }, runUrl: "https://app.calma.dev/runs/x",
  });
  srv.close();
  assert.ok(out.emitted && out.status === 200, "OTLP POST accepted (200)");
  assert.equal(cap.path, "/v1/traces");
  assert.equal(cap.ctype, "application/json");
  assert.equal(cap.auth, "Bearer k");
  const span = cap.body.resourceSpans[0].scopeSpans[0].spans[0];
  const kv = Object.fromEntries(span.attributes.map((x: any) => [x.key, x.value]));
  assert.equal(kv["calma.verdict"].stringValue, "REFUTED");
  assert.equal(kv["gen_ai.evaluation.outcome"].stringValue, "fail");
});
