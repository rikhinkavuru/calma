"""Dumb file-based store. Each edge writes its learning corpus here (A1 corrections, A3 constraints,
A4 episodes). Mirrors the engine's own .calma/*.jsonl breadcrumbs."""
import json, os
def append(path, record):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)            # a bare filename has an empty dirname -> skip makedirs
    with open(path, "a") as fh: fh.write(json.dumps(record, sort_keys=True) + "\n")
def iter_records(path):
    if not os.path.exists(path): return
    with open(path) as fh:                          # close the handle even on partial consumption
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue                        # tolerate a torn last line from a crashed writer
