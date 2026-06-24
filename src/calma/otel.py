"""calma.otel - the public facade for the OTel-eval distribution wedge (master roadmap §4 / P2-M7a).

Emit each Calma verdict as a standard OpenTelemetry GenAI *evaluation result* so any agent-observability
backend (Braintrust / LangSmith / Langfuse / Phoenix) ingests Calma as a drop-in DETERMINISTIC eval source
with zero custom integration.

    from calma.otel import emit_verdict, CalmaSpanProcessor
    emit_verdict(verdict_result, span=current_span, mode="event", dual_emit={"braintrust"})

Two emission modes, one firewall:
  * mode="event"  - records a `gen_ai.evaluation.result` span-EVENT on the current/given OTel span (spec-true;
                    requires the opentelemetry SDK + a live span).
  * mode="span"   - POSTs a standalone `gen_ai.evaluation.result` span over OTLP/HTTP, optionally LINKED to
                    the evaluated span. ZERO dependencies (pure stdlib) - the self-emit path.

The deterministic core never imports OpenTelemetry; the mapping + OTLP/JSON builder live in the pure-stdlib
engine module `otel_eval` and are re-exported here. The optional SDK is imported lazily, only for mode="event"
and the SpanProcessor - so `pip install calma` (no extras) still gives you the full self-emit wedge.
"""
from __future__ import annotations

import calma as _calma  # noqa: F401 - triggers the facade bootstrap (adds the engine dir to sys.path)
import otel_eval as _core  # noqa: E402 - the pure-stdlib mapping + OTLP builder + emitter

# re-export the zero-dependency core surface
map_verdict = _core.map_verdict
build_otlp_traces = _core.build_otlp_traces
dual_emit_attrs = _core.dual_emit_attrs
emit_otlp = _core.emit_otlp
VERDICT_MAP = _core.VERDICT_MAP
EVAL_NAME = _core._EVAL_NAME

__all__ = ["emit_verdict", "map_verdict", "build_otlp_traces", "dual_emit_attrs", "emit_otlp",
           "VERDICT_MAP", "EVAL_NAME", "CalmaSpanProcessor"]

_ENGINE_VERSION = getattr(_calma, "__version__", None)


def _otel_available():
    try:
        import opentelemetry.trace  # noqa: F401
        return True
    except Exception:
        return False


def emit_verdict(result, *, span=None, mode="span", endpoint=None, headers=None, dual_emit=(),
                 evaluated=None, run_url=None, engine_version=None, dry_run=False):
    """Emit a finished Calma verdict as an OTel GenAI evaluation result.

    mode="event": record a `gen_ai.evaluation.result` span-event on `span` (or the current span) - the
                  spec-true form. Requires the opentelemetry SDK; falls back to mode="span" if unavailable.
    mode="span"  (default): POST a standalone linked eval span over OTLP/HTTP (pure stdlib, no deps).

    `dual_emit` is an iterable of backend names; `evaluated` = {'trace_id','span_id'} to link the eval to the
    agent operation it scored. Returns a dict describing what was emitted.
    """
    engine_version = engine_version or _ENGINE_VERSION
    if mode == "event":
        ev = _emit_event(result, span=span, dual_emit=dual_emit, run_url=run_url,
                         engine_version=engine_version)
        if ev is not None:
            return ev
        # no SDK / no active span -> fall through to the standalone OTLP span (resilient by design)
    return _core.emit_verdict(result, endpoint=endpoint, headers=headers, dual_emit=tuple(dual_emit),
                              evaluated=evaluated, run_url=run_url, engine_version=engine_version,
                              dry_run=dry_run)


def _emit_event(result, *, span=None, dual_emit=(), run_url=None, engine_version=None):
    """Record the eval as a span-EVENT on a live OTel span. Returns the result dict, or None when the SDK or
    an active recording span is unavailable (so the caller can fall back to the OTLP standalone span)."""
    if not _otel_available():
        return None
    from opentelemetry import trace as _t
    target = span or _t.get_current_span()
    ctx = getattr(target, "get_span_context", lambda: None)()
    if target is None or ctx is None or not getattr(ctx, "is_valid", False):
        return None
    attrs = _core.map_verdict(result, run_url=run_url, engine_version=engine_version)
    if dual_emit:
        attrs = _core.dual_emit_attrs(attrs, list(dual_emit))
    # OTel span-event attributes must be scalars/sequences of scalars - map_verdict already yields scalars.
    target.add_event(_core._EVAL_NAME, attributes=attrs)
    outcome = attrs.get("gen_ai.evaluation.outcome")
    return {"emitted": True, "mode": "event", "outcome": outcome, "attributes": attrs}


class CalmaSpanProcessor:
    """A small config-carrying helper for wiring Calma as an eval source into an existing OTel pipeline.

    Construct it once with your endpoint / dual-emit choice, then call `.emit(verdict_result, span=...)` after
    each Calma verification. When the opentelemetry SDK + a live span are present it records the spec-true
    span-event; otherwise it POSTs a standalone OTLP span. It also conforms to the SpanProcessor lifecycle
    (no-op on_start/on_end) so it can be added to a TracerProvider without error; the auto-emit-on-verify hook
    is a documented follow-up. Honors OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS.
    """

    def __init__(self, *, endpoint=None, headers=None, dual_emit=(), mode="span", run_url=None):
        self.endpoint = endpoint
        self.headers = headers
        self.dual_emit = tuple(dual_emit)
        self.mode = mode
        self.run_url = run_url

    def emit(self, result, *, span=None, evaluated=None, mode=None, dry_run=False):
        return emit_verdict(result, span=span, mode=mode or self.mode, endpoint=self.endpoint,
                            headers=self.headers, dual_emit=self.dual_emit, evaluated=evaluated,
                            run_url=self.run_url, dry_run=dry_run)

    # --- SpanProcessor lifecycle (no-ops; present so the processor can be registered on a provider) ---
    def on_start(self, span, parent_context=None):
        return None

    def on_end(self, span):
        return None

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis=30000):
        return True
