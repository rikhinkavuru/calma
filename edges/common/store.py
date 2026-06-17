"""Dumb file-based store. Each edge writes its learning corpus here (A1 corrections, A3 constraints,
A4 episodes). Mirrors the engine's own .calma/*.jsonl breadcrumbs."""
import json, os
def append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh: fh.write(json.dumps(record, sort_keys=True) + "\n")
def iter_records(path):
    if not os.path.exists(path): return
    for line in open(path):
        line = line.strip()
        if line: yield json.loads(line)
