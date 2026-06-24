"""control_plane.api.engine — the bridge to the pure-stdlib engine. The API NEVER reimplements verify;
it stages the bundle+data into a workdir, runs `calma verify --json` (the whole engine pipeline: run →
recompute → validity → verdict), parses the stable JSON, then stores artifacts + evidence in R2.
Recompute happens host-side inside the engine, outside any sandbox — the load-bearing invariant."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile

from . import config, storage


def _safe_join(base, rel):
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the workdir: %r" % rel)
    return full


def _safe_extract(tar_path, dest):
    with tarfile.open(tar_path) as tf:
        for m in tf.getmembers():
            _safe_join(dest, m.name)          # raises on traversal
        tf.extractall(dest)                   # nosec: members pre-validated above


def prepare_workdir(tenant_id, bundle_key, data_refs):
    """Download + extract the bundle and stage data_refs into a fresh workdir."""
    work = tempfile.mkdtemp(prefix="calma_job_")
    btar = os.path.join(work, "_bundle.tar.gz")
    storage.download_to(bundle_key, btar)
    _safe_extract(btar, work)
    os.remove(btar)
    for dr in data_refs:
        dest = _safe_join(work, dr.dest_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        storage.download_to(dr.uri, dest)
    return work


def contract_sha256_hex(work):
    """sha256 of the bundle's verify.yaml (the contract), or '' if absent."""
    import hashlib
    p = os.path.join(work, "verify.yaml")
    if not os.path.isfile(p):
        return ""
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run_verify(work, trust, wall_seconds=120):
    """Run the engine over the prepared workdir. Returns (result_dict_or_None, stdout, stderr, rc)."""
    trust_flag = "third-party" if trust == "untrusted-third-party" else "own-code"
    cmd = [config.ENGINE_PYTHON, config.ENGINE_SCRIPT, "verify", work, "--json", "--trust", trust_flag]
    # On a host without a local sandbox, pin the isolation tier (e.g. e2b) so untrusted runs reach a verified
    # microVM instead of fail-closed REFUSE. Empty/auto -> the engine picks the best local tier (dev hosts).
    if config.EXEC_ISOLATION and config.EXEC_ISOLATION != "auto":
        cmd += ["--isolation", config.EXEC_ISOLATION]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_seconds + 30, cwd=work)
    except subprocess.TimeoutExpired:
        return None, "", "engine wall-clock timeout", -9
    result = None
    try:
        result = json.loads(p.stdout)
    except (ValueError, TypeError):
        pass
    return result, p.stdout, p.stderr, p.returncode


def collect_and_store(work, tenant_id, job_id, run_id, json_result):
    """Upload run artifacts (work/runs/**) + the structured evidence to R2; return (manifest, proof_key)."""
    manifest = []
    runs_dir = os.path.join(work, "runs")
    if os.path.isdir(runs_dir):
        for root, _dirs, files in os.walk(runs_dir):
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, runs_dir)
                key = storage.tenant_key(tenant_id, "artifacts", job_id, run_id, rel)
                try:
                    storage.upload_file(fp, key)
                    manifest.append({"name": rel, "size": os.path.getsize(fp), "key": key})
                except Exception:
                    pass
    proof_key = storage.tenant_key(tenant_id, "proofs", "%s.json" % job_id)
    evidence = {"verification_id": job_id, "run_id": run_id, "result": json_result,
                "artifacts": manifest}
    storage.put_bytes(proof_key, json.dumps(evidence, indent=2).encode("utf-8"), "application/json")
    return manifest, proof_key


def cleanup(work):
    shutil.rmtree(work, ignore_errors=True)
