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


def intoto_statement(manifest, subject_name, verdict, scope=None):
    """An in-toto/SLSA-style attestation statement binding the verdict to the content-addressed inputs.
    Aligns to in-toto Statement v1 so it drops into SLSA/sigstore provenance pipelines."""
    scope = scope or {}
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": subject_name, "digest": {"sha256": manifest.get("manifest_sha256", "")}}],
        "predicateType": "https://calma.dev/attestation/verification/v1",
        "predicate": {
            "builder": {"id": "https://calma.dev/skill"},
            "verdict": verdict,
            "isolation_tier": scope.get("isolation_tier"),
            "determinism_mode": scope.get("determinism_mode"),
            "reproducibility_scope": scope.get("reproducibility_scope"),
            "materials": [{"uri": f["path"], "digest": {"sha256": f["sha256"]}}
                          for f in manifest.get("files", [])],
        },
    }


def ml_bom(manifest, target, scope=None):
    """A CycloneDX ML-BOM (machine-learning bill of materials) - the artifact AI-BOM procurement rules
    and EU AI Act Art. 11 increasingly require: every input hashed, with the verification posture stamped."""
    scope = scope or {}
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {"component": {"type": "machine-learning-model", "name": target,
                                   "bom-ref": "calma:" + (manifest.get("manifest_sha256", "")[:16])}},
        "components": [{"type": "data", "name": f["path"], "bom-ref": f["path"],
                        "hashes": [{"alg": "SHA-256", "content": f["sha256"]}]}
                       for f in manifest.get("files", [])],
        "properties": [
            {"name": "calma:isolation_tier", "value": str(scope.get("isolation_tier"))},
            {"name": "calma:determinism_mode", "value": str(scope.get("determinism_mode"))},
            {"name": "calma:manifest_sha256", "value": manifest.get("manifest_sha256", "")},
        ],
    }
