# Calma control-plane — starter SLOs (D9-02)
*Signals to Sentry (errors + transaction latency/throughput) + Vercel function metrics (saturation). Error
budget = (1 − SLO) × window. Tighten once there's real baseline traffic.*

| SLI | SLO (monthly) | Source | Alert |
|---|---|---|---|
| **Availability** — non-5xx on `/v1/verifications` + `/healthz` | ≥ 99.5% | Sentry tx + Vercel | error budget burn > 2×/24h |
| **Errors** — unhandled 5xx rate | < 0.5% of requests | Sentry issues | any new issue; rate > 0.5% |
| **Latency** — control-plane overhead p95 (request time minus the engine subprocess) | < 1s | Sentry tx duration | p95 > 1s for 15m |
| **Latency** — end-to-end verify p95 (incl. E2B boot + recompute) | < 90s | Sentry tx duration | p95 > 90s for 15m |
| **Saturation** — active jobs vs the global ceiling (20) | < 80% sustained | `calma_active_job_count` / Vercel | ≥ 80% for 10m |

Not yet covered (needs the async fabric / more infra): queue depth, worker saturation, R2/Supabase
dependency SLOs. Pages route to the founder until an on-call rotation exists (IR runbook: TODO).
