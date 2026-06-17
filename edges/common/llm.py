"""Thin Anthropic wrapper. The ONLY place edges talk to a model. Every structured call is
schema-validated at the boundary and retried with the validation error fed back — the same
propose→check→counterexample discipline used everywhere downstream, applied to JSON validity."""
import json, os, hashlib
import anthropic
from edges.common import record

OPUS   = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

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
    """Plain text completion. Deterministic by default (temperature 0). Goes through record/replay."""
    req = {"model": model, "system": system, "max_tokens": max_tokens,
           "temperature": temperature, "messages": [{"role": "user", "content": prompt}]}
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
    req0 = {"model": model, "system": system, "max_tokens": max_tokens, "temperature": 0.0,
            "tools": tools, "tool_choice": {"type": "tool", "name": tool_name},
            "messages": [{"role": "user", "content": prompt}]}
    messages = list(req0["messages"])
    for attempt in range(retries + 1):
        req = dict(req0, messages=messages)
        cached = record.replay(req)
        if cached is not None:
            data = cached
        else:
            msg = _c().messages.create(**{k: v for k, v in req.items() if v is not None})
            tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
            data = tool_use.input if tool_use else {}
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
