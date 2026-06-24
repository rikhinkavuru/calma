# Wiring Calma into your eval backend

`@calma/otel` (and the Python `calma.otel`) emit each verdict as a standard OTel `gen_ai.evaluation.result`
span. Point it at your backend's OTLP endpoint and you're done. Recipes below are pinned to the build-plan
spec (§4.4) — **verify against the backend's current OTLP docs before use**, endpoints do change.

`adapterConfig(backend)` (TS) / `adapter_config(backend)` (Python) returns the exact endpoint, header
template, the env vars to set, whether the backend reads `gen_ai.*` natively (else it needs a
native-namespace dual-emit), and a ready-to-paste `OTEL_EXPORTER_OTLP_*` block.

| Backend | OTLP endpoint | Auth | Reads `gen_ai.*` natively? |
|---|---|---|---|
| **Braintrust** | `https://api.braintrust.dev/otel` | `Authorization: Bearer $BRAINTRUST_API_KEY` · `x-bt-parent: project_name:$BRAINTRUST_PROJECT` | No → dual-emit `braintrust.*` |
| **LangSmith** | `https://api.smith.langchain.com/otel` | `x-api-key: $LANGSMITH_API_KEY` | No → dual-emit `langsmith.*` |
| **Langfuse** | `https://cloud.langfuse.com/api/public/otel` | `Authorization: Basic base64(pk:sk)` · `x-langfuse-ingestion-version: 4` | **Yes** — canonical mapping is enough |
| **Phoenix** | `$PHOENIX_COLLECTOR_ENDPOINT` | `api_key=$PHOENIX_API_KEY` (cloud) | **Yes** (`label`/`score`) |

## Example (Braintrust)

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.braintrust.dev/otel"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $BRAINTRUST_API_KEY,x-bt-parent=project_name:$BRAINTRUST_PROJECT"
```

```ts
import { emitVerdict, adapterConfig } from "@calma/otel";
const a = adapterConfig("braintrust");           // -> { endpoint, headers, dualEmit, env, otelEnv, ... }
await emitVerdict(res, { dualEmit: a.dualEmit }); // endpoint/headers from the env block above
```

```python
from calma.otel import emit_verdict, adapter_config
a = adapter_config("braintrust")                  # -> {endpoint, headers, dual_emit, env, otel_env, ...}
emit_verdict(res, dual_emit=a["dual_emit"])        # honors $OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS
```

Backends that read `gen_ai.*` (Langfuse, Phoenix) need no `dualEmit`. The hosted Calma product's
settings/integrations screen generates this block per org, pre-filled — this module is the buildable core
behind it.
