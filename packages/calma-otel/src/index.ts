/**
 * @calma/otel — emit a finished Calma verdict as a standard OpenTelemetry GenAI *evaluation result*, so any
 * agent-observability backend (Braintrust / LangSmith / Langfuse / Phoenix) ingests Calma as a drop-in
 * DETERMINISTIC eval source. The TypeScript half of the OTel-eval distribution wedge (master roadmap §4 /
 * P2-M7a) — a faithful mirror of the Python `calma.otel` (scripts/otel_eval.py), same mapping, same redaction.
 *
 * FIREWALL: this only CONSUMES a finished verdict; it never derives one. Zero hard dependency — the self-emit
 * path uses global `fetch` + `node:crypto` only; the optional `@opentelemetry/api` is dynamically imported
 * for the span-EVENT mode and absence is handled (falls back to a standalone OTLP span).
 *
 * REDACTION BY CONSTRUCTION: `mapVerdict` copies a strict whitelist (verdict, metric, claimed, recomputed,
 * gap, budget, isolation, determinism, version, run_url, bundle hash, confidence, reason). No raw data, no
 * verdict_inputs vector ever reaches a span.
 */
import { createHash } from "node:crypto";

export type CalmaVerdict =
  | "CONFIRMED" | "CONFIRMED-WITH-CAVEATS" | "REFUTED" | "INVALIDATED"
  | "FLAG_FOR_DECLARATION" | "MIXED" | "INCONCLUSIVE" | "CAN'T-CONFIRM";

/** A finished verdict — either an engine ledger (repo_verdict + claims) or a flat run-result. */
export interface VerdictResult {
  repo_verdict?: CalmaVerdict;
  verdict?: CalmaVerdict;
  claims?: Array<Record<string, unknown>>;
  scope?: { isolation_tier?: string; determinism_mode?: string };
  metric?: string;
  claimed?: number; claimed_value?: number;
  recomputed?: number; recomputed_value?: number;
  reason?: string;
  confidence?: number; headline_confidence?: number;
  gap?: number;
  effective_budget?: number;
  isolation_tier?: string;
  determinism_mode?: string;
  engine_version?: string;
  run_url?: string;
  bundle_sha256?: string; manifest_ref?: string;
  run_id?: string; verification_id?: string;
}

export type Attrs = Record<string, string | number | boolean>;

export const EVAL_NAME = "gen_ai.evaluation.result";
const SCOPE_NAME = "@calma/otel";

/** verdict -> [score.label | null, outcome]. label=null => OMIT score.label (CAN'T-CONFIRM never asserts
 *  pass/fail). INVALIDATED and FLAG_FOR_DECLARATION map outcome=block (CANONICAL-DECISIONS §3). */
export const VERDICT_MAP: Record<string, [string | null, string]> = {
  "CONFIRMED": ["pass", "pass"],
  "CONFIRMED-WITH-CAVEATS": ["pass", "pass"],
  "REFUTED": ["fail", "fail"],
  "INVALIDATED": ["fail", "block"],
  "FLAG_FOR_DECLARATION": ["fail", "block"],
  "MIXED": ["fail", "fail"],
  "INCONCLUSIVE": [null, "allow"],
  "CAN'T-CONFIRM": [null, "allow"],
};

// OTLP span status: 0=UNSET, 1=OK, 2=ERROR. A catch (fail/block) -> ERROR; pass -> OK; allow -> UNSET.
const STATUS: Record<string, number> = { pass: 1, fail: 2, block: 2, allow: 0 };

interface Fields {
  verdict?: string; metric?: string; claimed?: number; recomputed?: number; reason?: string;
  confidence?: number; gap?: number; effective_budget?: number; isolation_tier?: string;
  determinism_mode?: string; engine_version?: string; run_url?: string; bundle_sha256?: string;
  run_id?: string;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function extract(result: VerdictResult): Fields {
  if ("repo_verdict" in result || "claims" in result) {            // a ledger
    const claims = (result.claims ?? []) as Array<Record<string, unknown>>;
    const head = (claims.find((c) => c.headline) ?? claims[0] ?? {}) as Record<string, unknown>;
    const vi = (head.verdict_inputs ?? {}) as Record<string, unknown>;
    const scope = result.scope ?? {};
    return {
      verdict: result.repo_verdict,
      metric: head.metric as string | undefined,
      claimed: num(head.claimed_value),
      recomputed: num(head.recomputed_value),
      reason: head.reason as string | undefined,
      confidence: num(head.headline_confidence),
      gap: num(vi.gap),
      effective_budget: num(vi.effective_budget),
      isolation_tier: (vi.isolation_tier as string) ?? scope.isolation_tier,
      determinism_mode: (vi.determinism_mode as string) ?? scope.determinism_mode,
      engine_version: result.engine_version,
      run_url: result.run_url,
      bundle_sha256: result.bundle_sha256 ?? result.manifest_ref,
      run_id: result.run_id ?? result.verification_id,
    };
  }
  return {                                                          // a flat run-result
    verdict: result.verdict,
    metric: result.metric,
    claimed: num(result.claimed ?? result.claimed_value),
    recomputed: num(result.recomputed ?? result.recomputed_value),
    reason: result.reason,
    confidence: num(result.confidence ?? result.headline_confidence),
    gap: num(result.gap),
    effective_budget: num(result.effective_budget),
    isolation_tier: result.isolation_tier,
    determinism_mode: result.determinism_mode,
    engine_version: result.engine_version,
    run_url: result.run_url,
    bundle_sha256: result.bundle_sha256 ?? result.manifest_ref,
    run_id: result.run_id ?? result.verification_id,
  };
}

export interface MapOpts { runUrl?: string; engineVersion?: string; }

/** A finished verdict -> the flat OTel GenAI-eval attribute object. Redaction by construction. */
export function mapVerdict(result: VerdictResult, opts: MapOpts = {}): Attrs {
  const f = extract(result);
  const [label, outcome] = VERDICT_MAP[f.verdict ?? ""] ?? [null, "allow"]; // unknown -> never asserts pass/fail
  const attrs: Attrs = {
    "gen_ai.operation.name": "evaluation",
    "gen_ai.system": "calma",
    "gen_ai.evaluation.name": `calma.${f.metric ?? "result"}`,
    "gen_ai.evaluation.outcome": outcome,
    "calma.verdict": f.verdict ?? "",
    "calma.evaluator": "calma",
  };
  if (f.recomputed !== undefined) attrs["gen_ai.evaluation.score.value"] = f.recomputed;
  if (label !== null) attrs["gen_ai.evaluation.score.label"] = label;
  if (f.reason) attrs["gen_ai.evaluation.explanation"] = f.reason;
  const native: Array<[string, string | number | undefined]> = [
    ["calma.confidence", f.confidence],
    ["calma.claimed", f.claimed],
    ["calma.recomputed", f.recomputed],
    ["calma.gap", f.gap],
    ["calma.effective_budget", f.effective_budget],
    ["calma.isolation_tier", f.isolation_tier],
    ["calma.determinism_mode", f.determinism_mode],
    ["calma.engine_version", opts.engineVersion ?? f.engine_version],
    ["calma.run_url", opts.runUrl ?? f.run_url],
    ["calma.bundle_sha256", f.bundle_sha256],
  ];
  for (const [k, v] of native) if (v !== undefined && v !== null) attrs[k] = v;
  return attrs;
}

/** Mirror the verdict into a backend's NATIVE namespace on the same span (Braintrust/LangSmith), so backends
 *  that don't yet read gen_ai.* still ingest it. Langfuse/Phoenix read gen_ai.* natively -> no mirror. */
export function dualEmitAttrs(attrs: Attrs, backends: string[]): Attrs {
  const out: Attrs = { ...attrs };
  const name = String(attrs["gen_ai.evaluation.name"] ?? "calma.result");
  const outcome = String(attrs["gen_ai.evaluation.outcome"] ?? "allow");
  const score01 = outcome === "pass" ? 1.0 : outcome === "fail" || outcome === "block" ? 0.0 : undefined;
  const meta: Record<string, unknown> = {};
  for (const k of Object.keys(attrs)) if (k.startsWith("calma.")) meta[k.slice(6)] = attrs[k];
  for (const b of backends.map((x) => x.trim().toLowerCase())) {
    if (b === "braintrust") {
      out["braintrust.span_attributes"] = JSON.stringify({ type: "score", name });
      if (score01 !== undefined) out["braintrust.scores"] = JSON.stringify({ calma: score01 });
      out["braintrust.metadata"] = JSON.stringify(meta);
    } else if (b === "langsmith") {
      out["langsmith.span.kind"] = "EVALUATOR";
      out["langsmith.metadata.calma_verdict"] = String(attrs["calma.verdict"] ?? "");
    }
  }
  return out;
}

// --- Per-backend adapter recipes (master roadmap §4.4): the exact OTLP endpoint + auth-header template + the
// native dual-emit each backend needs, so wiring Calma in is copy-paste. Pinned to the build-plan spec — verify
// against the backend's current OTLP docs before use. ${VAR} placeholders name the env vars the user supplies.
export interface Adapter {
  endpoint: string; headers: Record<string, string>; dualEmit: string[];
  env: string[]; readsGenAi: boolean; note: string;
}

export const ADAPTERS: Record<string, Adapter> = {
  braintrust: {
    endpoint: "https://api.braintrust.dev/otel",
    headers: { Authorization: "Bearer ${BRAINTRUST_API_KEY}", "x-bt-parent": "project_name:${BRAINTRUST_PROJECT}" },
    dualEmit: ["braintrust"],
    env: ["BRAINTRUST_API_KEY", "BRAINTRUST_PROJECT"],
    readsGenAi: false,
    note: "Braintrust has no native GenAI-eval reader; the calma score rides its braintrust.* namespace.",
  },
  langsmith: {
    endpoint: "https://api.smith.langchain.com/otel",
    headers: { "x-api-key": "${LANGSMITH_API_KEY}" },
    dualEmit: ["langsmith"],
    env: ["LANGSMITH_API_KEY"],
    readsGenAi: false,
    note: "the canonical gen_ai.* attributes ride along; langsmith.* discriminators route it today.",
  },
  langfuse: {
    endpoint: "https://cloud.langfuse.com/api/public/otel",
    headers: { Authorization: "Basic ${LANGFUSE_AUTH_B64}", "x-langfuse-ingestion-version": "4" },
    dualEmit: [],
    env: ["LANGFUSE_AUTH_B64"],
    readsGenAi: true,
    note: "Langfuse reads gen_ai.* natively; LANGFUSE_AUTH_B64 = base64(public_key:secret_key).",
  },
  phoenix: {
    endpoint: "${PHOENIX_COLLECTOR_ENDPOINT}",
    headers: { api_key: "${PHOENIX_API_KEY}" },
    dualEmit: [],
    env: ["PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_API_KEY"],
    readsGenAi: true,
    note: "Phoenix reads label/score natively; a self-hosted collector needs no api_key.",
  },
};

/** The OTLP adapter recipe for a backend + a ready-to-paste OTEL_EXPORTER_OTLP_* env block. Throws on an
 *  unknown backend. Pure config projection — no network, no secrets. */
export function adapterConfig(backend: string): Adapter & { otelEnv: Record<string, string> } {
  const b = (backend ?? "").trim().toLowerCase();
  const rec = ADAPTERS[b];
  if (!rec) throw new Error(`unknown backend '${backend}' (known: ${Object.keys(ADAPTERS).sort().join(", ")})`);
  const headers = Object.entries(rec.headers).map(([k, v]) => `${k}=${v}`).join(",");
  return { ...rec, otelEnv: { OTEL_EXPORTER_OTLP_ENDPOINT: rec.endpoint, OTEL_EXPORTER_OTLP_HEADERS: headers } };
}

// --- OTLP/HTTP JSON encoding (the zero-dep transport). trace_id/span_id are HEX per the OTLP/JSON spec. ---

function anyValue(v: string | number | boolean): Record<string, unknown> {
  if (typeof v === "boolean") return { boolValue: v };
  if (typeof v === "number") return Number.isInteger(v) ? { intValue: String(v) } : { doubleValue: v };
  return { stringValue: String(v) };
}
function kv(d: Attrs): Array<Record<string, unknown>> {
  return Object.entries(d).map(([key, value]) => ({ key, value: anyValue(value) }));
}

/** Deterministic (traceId, spanId) from a stable seed — so a redelivery of the SAME verdict overwrites. */
export function ids(seed: string): { traceId: string; spanId: string } {
  const h = createHash("sha256").update(seed, "utf8").digest("hex");
  return { traceId: h.slice(0, 32), spanId: h.slice(32, 48) };
}

export interface BuildOpts {
  name?: string; traceId: string; spanId: string; startUnixNano?: number; endUnixNano?: number;
  evaluatedTraceId?: string; evaluatedSpanId?: string; resourceAttrs?: Attrs; scopeVersion?: string;
}

/** The OTLP/HTTP JSON traces payload: a standalone gen_ai.evaluation.result span, optionally LINKED to the
 *  evaluated agent span. Pure (the caller supplies ids + timestamps), so it is deterministic + testable. */
export function buildOtlpTraces(attrs: Attrs, o: BuildOpts): unknown {
  const outcome = String(attrs["gen_ai.evaluation.outcome"] ?? "allow");
  const span: Record<string, unknown> = {
    traceId: o.traceId,
    spanId: o.spanId,
    name: o.name ?? EVAL_NAME,
    kind: 1,
    startTimeUnixNano: String(o.startUnixNano ?? 0),
    endTimeUnixNano: String(o.endUnixNano ?? 0),
    attributes: kv(attrs),
    status: { code: STATUS[outcome] ?? 0 },
  };
  if (o.evaluatedTraceId && o.evaluatedSpanId) {
    span.links = [{ traceId: o.evaluatedTraceId, spanId: o.evaluatedSpanId }];
  }
  return {
    resourceSpans: [{
      resource: { attributes: kv(o.resourceAttrs ?? { "service.name": "calma" }) },
      scopeSpans: [{ scope: { name: SCOPE_NAME, version: o.scopeVersion ?? "" }, spans: [span] }],
    }],
  };
}

function parseOtlpHeaders(s: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (s ?? "").split(",")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

export interface EmitOpts {
  endpoint?: string; headers?: Record<string, string>; dualEmit?: string[];
  evaluated?: { traceId?: string; spanId?: string }; runUrl?: string; engineVersion?: string;
  dryRun?: boolean; timeoutMs?: number;
}

/** POST an OTLP payload to <endpoint>/v1/traces. Honors OTEL_EXPORTER_OTLP_ENDPOINT / *_HEADERS so the user
 *  points it at THEIR backend. Returns the HTTP status, or null when nothing is configured (honest no-op). */
export async function emitOtlp(payload: unknown, opts: EmitOpts = {}): Promise<number | null> {
  const endpoint = opts.endpoint ?? process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  if (!endpoint) return null;
  let url = endpoint.replace(/\/+$/, "");
  if (!url.endsWith("/v1/traces")) url += "/v1/traces";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  Object.assign(headers, parseOtlpHeaders(process.env.OTEL_EXPORTER_OTLP_HEADERS), opts.headers ?? {});
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 5000);
  try {
    const resp = await fetch(url, { method: "POST", headers, body: JSON.stringify(payload), signal: ctrl.signal });
    return resp.status;
  } finally {
    clearTimeout(t);
  }
}

function seedOf(result: VerdictResult, attrs: Attrs): string {
  const f = extract(result);
  if (f.run_id) return `calma:run:${f.run_id}`;
  if (attrs["calma.bundle_sha256"]) return `calma:bundle:${attrs["calma.bundle_sha256"]}`;
  return "calma:attrs:" + JSON.stringify(attrs, Object.keys(attrs).sort());
}

export interface EmitResult {
  payload: unknown; emitted: boolean; status: number | null; traceId: string; spanId: string;
}

/** The one-call self-emit: map a finished verdict -> an OTel eval span -> OTLP POST. `dualEmit` names backends
 *  to mirror; `evaluated` links the eval to the agent operation it scored; `dryRun` builds without POSTing. */
export async function emitVerdict(result: VerdictResult, opts: EmitOpts = {}): Promise<EmitResult> {
  let attrs = mapVerdict(result, { runUrl: opts.runUrl, engineVersion: opts.engineVersion });
  if (opts.dualEmit?.length) attrs = dualEmitAttrs(attrs, opts.dualEmit);
  const { traceId, spanId } = ids(seedOf(result, attrs));
  const now = opts.dryRun ? 0 : Date.now() * 1e6;            // ms -> ns
  const payload = buildOtlpTraces(attrs, {
    traceId, spanId, startUnixNano: now, endUnixNano: now,
    evaluatedTraceId: opts.evaluated?.traceId, evaluatedSpanId: opts.evaluated?.spanId,
    scopeVersion: opts.engineVersion ?? "",
  });
  const status = opts.dryRun ? null : await emitOtlp(payload, opts);
  return { payload, emitted: status !== null, status, traceId, spanId };
}

/** A small config-carrying helper for wiring Calma as an eval source into an existing OTel pipeline. When the
 *  optional @opentelemetry/api is present and a live span is given, it records the spec-true span-EVENT;
 *  otherwise it POSTs a standalone OTLP span. The auto-emit-on-verify hook is a documented follow-up. */
export class CalmaSpanProcessor {
  private readonly cfg: EmitOpts;
  constructor(cfg: EmitOpts = {}) {        // explicit field (not a TS parameter property — Node strip-only mode)
    this.cfg = cfg;
  }

  async emit(result: VerdictResult, extra: { span?: unknown; mode?: "event" | "span" } = {}): Promise<EmitResult | { emitted: true; mode: "event"; attributes: Attrs }> {
    if (extra.mode === "event" && extra.span) {
      const attrs = (() => {
        let a = mapVerdict(result, { runUrl: this.cfg.runUrl, engineVersion: this.cfg.engineVersion });
        if (this.cfg.dualEmit?.length) a = dualEmitAttrs(a, this.cfg.dualEmit);
        return a;
      })();
      const sp = extra.span as { addEvent?: (n: string, a: Attrs) => void };
      if (typeof sp.addEvent === "function") {
        sp.addEvent(EVAL_NAME, attrs);
        return { emitted: true, mode: "event", attributes: attrs };
      }
    }
    return emitVerdict(result, this.cfg);
  }

  // SpanProcessor lifecycle no-ops, so it can be registered on a TracerProvider without error.
  onStart(): void {}
  onEnd(): void {}
  async shutdown(): Promise<void> {}
  async forceFlush(): Promise<void> {}
}
