"""JSON Schema construction helpers shared by every edge that calls llm.structured.

Each A1–A4 edge forces the model through a single tool whose input_schema is a JSON Schema; hand
-building those dicts is verbose and easy to get subtly wrong, so the small constructors here keep
them declarative and consistent. Pure data — no model, no engine, no I/O — so it sits safely on the
edge side of the determinism firewall (it touches none of the forbidden core modules).

    from edges.common import schema as S
    EMIT = S.obj({
        "label":  S.enum("yes", "no", "unsure", description="the decision"),
        "score":  S.number(minimum=0, maximum=1),
        "reasons": S.array(S.string(), min_items=1),
    })
    data = llm.structured(prompt, schema=EMIT)
"""

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def obj(properties, required=None, *, additional=False, description=None):
    """An object schema. `required` defaults to EVERY declared property — the strict default we want
    for tool inputs so the model can't silently drop a field; pass an explicit list to relax it."""
    s = {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties.keys()) if required is None else list(required),
        "additionalProperties": additional,
    }
    if description:
        s["description"] = description
    return s


def array(items, *, min_items=None, max_items=None, description=None):
    s = {"type": "array", "items": items}
    if min_items is not None:
        s["minItems"] = min_items
    if max_items is not None:
        s["maxItems"] = max_items
    if description:
        s["description"] = description
    return s


def string(*, enum=None, pattern=None, description=None):
    s = {"type": "string"}
    if enum is not None:
        s["enum"] = list(enum)
    if pattern is not None:
        s["pattern"] = pattern
    if description:
        s["description"] = description
    return s


def number(*, integer=False, minimum=None, maximum=None, description=None):
    s = {"type": "integer" if integer else "number"}
    if minimum is not None:
        s["minimum"] = minimum
    if maximum is not None:
        s["maximum"] = maximum
    if description:
        s["description"] = description
    return s


def boolean(*, description=None):
    s = {"type": "boolean"}
    if description:
        s["description"] = description
    return s


def enum(*values, description=None):
    """A closed string enum — the most common edge-output shape (labels, categories)."""
    return string(enum=list(values), description=description)
