"""calma.attest - content-addressed SBOM re-run manifest. SHA-256 over sorted `relpath:sha256`
lines (the manifest's own hash excluded). Lets a verdict be independently re-checked.

Library: manifest_for(dir) -> dict. CLI: attest.py --run DIR [--out manifest.json]
"""
import argparse
import hashlib
import json
import os
import sys


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_for(root):
    files = []
    for dirpath, _, names in os.walk(root):
        for n in sorted(names):
            if n == "manifest.json":
                continue
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, root)
            files.append((rel, _sha256(full)))
    files.sort()
    lines = "".join("%s:%s\n" % (r, h) for r, h in files)
    root_hash = hashlib.sha256(lines.encode()).hexdigest()
    return {"root": os.path.basename(os.path.abspath(root)),
            "files": [{"path": r, "sha256": h} for r, h in files],
            "manifest_sha256": root_hash}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    man = manifest_for(a.run)
    text = json.dumps(man, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
