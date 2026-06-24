# @calma/otel

Emit a finished **Calma** verdict as a standard **OpenTelemetry GenAI evaluation result** — so any
agent-observability backend (Braintrust / LangSmith / Langfuse / Phoenix) ingests Calma as a **drop-in
deterministic eval source** with zero custom integration. The TypeScript half of Calma's OTel-eval
distribution wedge; a faithful mirror of the Python `calma.otel` (`from calma.otel import emit_verdict`).

```ts
import { emitVerdict, CalmaSpanProcessor } from "@calma/otel";

// after a Calma verification lands (a ledger or run-result `res`):
await emitVerdict(res, {
  endpoint: process.env.OTEL_EXPORTER_OTLP_ENDPOINT, // or rely on the env var
  dualEmit: ["braintrust"],                          // optional native-namespace mirror
});
```

## What it emits

A `gen_ai.evaluation.result` span over OTLP/HTTP (`fetch`, **no dependency on the OpenTelemetry SDK**):

- `gen_ai.evaluation.name` = `calma.<metric>`
- `gen_ai.evaluation.score.value` = the recomputed number (the determinism payoff)
- `gen_ai.evaluation.score.label` + `.outcome` from the verdict — `CONFIRMED→pass/pass`,
  `REFUTED→fail/fail`, `INVALIDATED`/`FLAG_FOR_DECLARATION`→`fail/block`, `CAN'T-CONFIRM`→omit-label/`allow`
- `gen_ai.evaluation.explanation` = the engine's reason line
- `calma.*` differentiators (confidence, claimed, recomputed, gap, isolation_tier, engine_version, run_url, …)

**Redaction by construction** — only the whitelist above leaves; no raw data ever reaches a span.
**Idempotent** — the span id is derived from the run id, so a redelivery overwrites. Honors the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS`.

`mode: "event"` with a live OTel span records the spec-true span-event (needs `@opentelemetry/api`, an
optional peer); otherwise a standalone linked OTLP span is POSTed.

## Status

`src/` ships as TypeScript (Node ≥22.6 strips types; bundlers handle `.ts`). `npm test` runs the suite via
`node --test`. A `tsc` build to `dist/` (ESM + CJS + `.d.ts`) and npm publish are a follow-up.
