"""Thin Anthropic wrapper. The ONLY place edges talk to a model. Every structured call is
schema-validated at the boundary and retried with the validation error fed back — the same
propose→check→counterexample discipline used everywhere downstream, applied to JSON validity."""
import json, os, hashlib
import anthropic
from edges.common import record

OPUS   = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

# Opus 4.7/4.8 (and Fable 5) reject sampling params (temperature/top_p/top_k) with a 400. Send
# `temperature` only to models that accept it -- OPUS gets none. Determinism here comes from
# record/replay, not temperature=0, so omitting it changes nothing about reproducibility. Haiku/Sonnet
# keep temperature, so their already-recorded fixture hashes are unchanged.
_NO_SAMPLING = {OPUS}

_client = None
def _c():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (or run with CALMA_EDGES_RECORD unset to replay fixtures)")
        _client = anthropic.Anthropic(api_key=key)
    return _client

def complete(prompt, *, model=SONNET, system=None, max_tokens=4096, temperature=0.0):
    """Plain text completion. Determinism comes from record/replay. `temperature` is sent only to
    models that accept it (omitted for OPUS, which 400s on sampling params)."""
    req = {"model": model, "system": system, "max_tokens": max_tokens,
           "messages": [{"role": "user", "content": prompt}]}
    if model not in _NO_SAMPLING:
        req["temperature"] = temperature
    cached = record.replay(req)
    if cached is not None:
        return cached
    msg = _c().messages.create(**{k: v for k, v in req.items() if v is not None})
    text = "".join(b.text for b in msg.content if b.type == "text")
    record.save(req, text)
    return text

def structured(prompt, *, schema, model=SONNET, system=None, max_tokens=4096,
               tool_name="emit", retries=2):
    """Force the model to call a single tool whose input_schema == `schema`; return the validated
    dict. On schema-invalid output, re-ask with the jsonschema error appended (counterexample loop).
    Raises after `retries`."""
    from jsonschema import validate, ValidationError
    tools = [{"name": tool_name, "description": "Emit the result.", "input_schema": schema}]
    req0 = {"model": model, "system": system, "max_tokens": max_tokens,
            "tools": tools, "tool_choice": {"type": "tool", "name": tool_name},
            "messages": [{"role": "user", "content": prompt}]}
    if model not in _NO_SAMPLING:
        req0["temperature"] = 0.0
    messages = list(req0["messages"])
    for attempt in range(retries + 1):
        req = dict(req0, messages=messages)
        cached = record.replay(req)
        if cached is not None:
            data = cached
        else:
            msg = _c().messages.create(**{k: v for k, v in req.items() if v is not None})
            tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
            if tool_use is None:
                # the model refused or truncated before the tool call -> NOT a valid structured result
                # (an empty {} would silently pass a schema with no required fields). Re-ask / raise; never
                # record a bogus fixture.
                if attempt == retries:
                    raise RuntimeError("model returned no `%s` tool call after %d attempts"
                                       % (tool_name, retries + 1))
                messages = messages + [
                    {"role": "user", "content": "You did not call the `%s` tool. Call it now with the "
                                                "result." % tool_name}]
                continue
            data = tool_use.input
            record.save(req, data)
        try:
            validate(instance=data, schema=schema)
            return data
        except ValidationError as e:
            if attempt == retries:
                raise
            messages = messages + [
                {"role": "assistant", "content": [{"type": "text", "text": json.dumps(data)}]},
                {"role": "user", "content": "That output failed schema validation: %s. "
                                            "Re-emit a corrected call." % e.message}]
    raise RuntimeError("unreachable")
