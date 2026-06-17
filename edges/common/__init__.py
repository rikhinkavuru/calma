"""edges.common — the shared scaffold every A1–A4 edge imports:

- llm     : the schema-forcing Anthropic client (the only place edges talk to a model)
- engine  : the black-box subprocess bridge to `calma verify`
- store   : the append-only JSONL learning substrate
- record  : the VCR-style record/replay shim (CI runs with no API key)
- schema  : JSON Schema builders for llm.structured calls

The package is physically isolated from the pure-stdlib core: edge code reaches the engine only
as a subprocess (see engine.py), proven by edges/tests/test_firewall.py.
"""
