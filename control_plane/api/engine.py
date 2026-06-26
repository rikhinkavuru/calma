"""control_plane.api.engine — the bridge to the pure-stdlib engine. The API NEVER reimplements verify;
it stages the bundle+data into a workdir, runs `calma verify --json` (the whole engine pipeline: run →
recompute → validity → verdict), parses the stable JSON, then stores artifacts + evidence in R2.
Recompute happens host-side inside the engine, outside any sandbox — the load-bearing invariant."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

from . import config, signing, storage

_HEX64 = re.compile(r"[0-9a-f]{64}")


def _sha256_file(path, chunk=1024 * 1024):
    """Streaming sha256 of a file (chunked — never loads a multi-GB bundle into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _verify_sha256(path, declared, what):
    """Reject downloaded bytes whose sha256 != the caller-declared hash (CWE-345). The control plane
    records and ATTESTS the declared hash, so the bytes it executes MUST be the bytes that hash to it:
    otherwise a tenant could PUT different bytes to the presigned object key and have Calma execute — and
    sign a proof over — content that does not match the hash stored in job metadata + the proof context.
    The storage layer does not independently enforce object-body checksums for these presigned PUTs."""
    declared = (declared or "").strip().lower()
    if not _HEX64.fullmatch(declared):
        raise ValueError("%s has no valid declared sha256 to verify the downloaded bytes against" % what)
    actual = _sha256_file(path)
    if actual != declared:
        raise ValueError("%s bytes do not match the declared sha256 (declared %s, computed %s)"
                         % (what, declared, actual))


def _safe_join(base, rel):
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the workdir: %r" % rel)
    return full


def _safe_extract(tar_path, dest):
    with tarfile.open(tar_path) as tf:
        for m in tf.getmembers():
            _safe_join(dest, m.name)          # raises on NAME traversal (../, absolute)
            # name validation alone does NOT catch a symlink/hardlink member whose *target* escapes dest
            # (a later member then writes THROUGH it). Reject link members outright.
            if m.issym() or m.islnk():
                raise ValueError("link member not allowed in bundle: %r -> %r" % (m.name, m.linkname))
        # filter='data' (PEP 706) blocks symlink/hardlink/absolute/device traversal independently of the
        # interpreter default — Vercel's Python 3.12 still defaults to 'fully_trusted' (only a warning),
        # so the explicit filter is defence-in-depth. BUT the `filter` kwarg only exists on Python 3.12+;
        # on older interpreters (the OSS engine runs on 3.9-3.11; cp-venv is 3.9) it raises TypeError, so
        # fall back to the name-validated + link-rejected extract above (still traversal-safe).
        try:
            tf.extractall(dest, filter="data")    # nosec: members name-validated + link-rejected + data filter
        except TypeError:
            tf.extractall(dest)                   # nosec: py<3.12 has no `filter` kwarg; guards above hold


def prepare_workdir(tenant_id, bundle_key, bundle_sha256, data_refs):
    """Download + extract the bundle and stage data_refs into a fresh workdir. EVERY downloaded object is
    hashed and checked against its caller-declared sha256 BEFORE it is extracted/used, so the bytes the
    engine executes are provably the bytes the control plane recorded (the bundle is verified before it is
    even unpacked — mismatched bytes are never extracted)."""
    work = tempfile.mkdtemp(prefix="calma_job_")
    btar = os.path.join(work, "_bundle.tar.gz")
    storage.download_to(bundle_key, btar)
    _verify_sha256(btar, bundle_sha256, "bundle")
    _safe_extract(btar, work)
    os.remove(btar)
    for dr in data_refs:
        dest = _safe_join(work, dr.dest_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        storage.download_to(dr.uri, dest)
        _verify_sha256(dest, dr.sha256, "data_ref %r" % dr.dest_rel)
    return work


def contract_sha256_hex(work):
    """sha256 of the bundle's verify.yaml (the contract), or '' if absent."""
    p = os.path.join(work, "verify.yaml")
    if not os.path.isfile(p):
        return ""
    return _sha256_file(p)


def run_verify(work, trust, wall_seconds=120):
    """Run the engine over the prepared workdir. Returns (result_dict_or_None, stdout, stderr, rc)."""
    trust_flag = "third-party" if trust == "untrusted-third-party" else "own-code"
    cmd = [config.ENGINE_PYTHON, config.ENGINE_SCRIPT, "verify", work, "--json", "--trust", trust_flag]
    # On a host without a local sandbox, pin the isolation tier (e.g. e2b) so untrusted runs reach a verified
    # microVM instead of fail-closed REFUSE. Empty/auto -> the engine picks the best local tier (dev hosts).
    if config.EXEC_ISOLATION and config.EXEC_ISOLATION != "auto":
        cmd += ["--isolation", config.EXEC_ISOLATION]
    env = dict(os.environ)
    if config.REQUIRE_VERIFIED_ISOLATION:
        # The control plane is a multi-tenant host: the engine must REFUSE (exit 3) rather than degrade
        # own-code to an unwrapped host run on a host without a verified sandbox tier. Tenant bytes never
        # execute unisolated on the API host.
        env["CALMA_REQUIRE_ISOLATED"] = "1"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_seconds + 30, cwd=work,
                           env=env)
    except subprocess.TimeoutExpired:
        return None, "", "engine wall-clock timeout", -9
    result = None
    try:
        result = json.loads(p.stdout)
    except (ValueError, TypeError):
        pass
    return result, p.stdout, p.stderr, p.returncode


def _safe_artifact(fp, runs_dir):
    """A discovered run-output path is collectable ONLY if it is a REGULAR file that physically lives
    under runs/. Rejects (returns None) symlinks, hardlinks, device nodes, FIFOs and sockets — a verified
    sandbox confines the RUN, but the host-side collector runs as the API process and would otherwise
    follow a planted `runs/leak -> /etc/passwd` (or `-> /proc/1/environ`) and upload host secrets to the
    tenant's artifact prefix. Returns the lstat on success."""
    try:
        st = os.lstat(fp)                      # lstat: never follow a final-component symlink
    except OSError:
        return None
    # regular file only (rejects symlink/FIFO/device/socket); nlink==1 rejects a hardlink that could
    # alias a host file outside runs/ (realpath can't undo a hardlink — only the link count reveals it);
    # realpath containment rejects anything whose resolved path escapes the canonical runs/ subtree.
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        return None
    if not os.path.realpath(fp).startswith(runs_dir + os.sep):
        return None
    return st


def collect_and_store(work, tenant_id, job_id, run_id, json_result):
    """Upload run artifacts (work/runs/**) + the structured evidence to R2; return (manifest, proof_key).
    Only regular files contained in runs/ are uploaded (see _safe_artifact); symlinks/hardlinks/special
    files are skipped, and the file count + total/per-file bytes are capped to bound a hostile output
    flood. The number skipped is recorded in the evidence so a truncation/skip is never silent."""
    manifest, skipped, total_bytes = [], 0, 0
    runs_dir = os.path.realpath(os.path.join(work, "runs"))
    if os.path.isdir(runs_dir) and not os.path.islink(os.path.join(work, "runs")):
        # followlinks=False + pruning symlinked subdirs: os.walk never descends a planted `runs/x -> /`.
        for root, dirs, files in os.walk(runs_dir, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                st = _safe_artifact(fp, runs_dir)
                if st is None or st.st_size > config.MAX_ARTIFACT_FILE_BYTES:
                    skipped += 1
                    continue
                if len(manifest) >= config.MAX_ARTIFACT_FILES \
                        or total_bytes + st.st_size > config.MAX_ARTIFACT_BYTES:
                    skipped += 1
                    continue
                rel = os.path.relpath(fp, runs_dir)
                key = storage.tenant_key(tenant_id, "artifacts", job_id, run_id, rel)
                try:
                    storage.upload_file(fp, key)
                    manifest.append({"name": rel, "size": st.st_size, "key": key})
                    total_bytes += st.st_size
                except Exception:
                    skipped += 1
    proof_key = storage.tenant_key(tenant_id, "proofs", "%s.json" % job_id)
    evidence = {"verification_id": job_id, "run_id": run_id, "result": json_result,
                "artifacts": manifest}
    if skipped:
        evidence["artifacts_skipped"] = skipped
    # The control-plane VOUCHES for the evidence: wrap it in a signed DSSE envelope (ed25519). Anyone can
    # verify the proof offline against the published public key — that signature is what makes the verdict
    # carry signal to a third party. Unsigned (no key configured) still yields a valid envelope, signatures:[].
    envelope = signing.sign_envelope(evidence)
    storage.put_bytes(proof_key, json.dumps(envelope, indent=2).encode("utf-8"), "application/json")
    return manifest, proof_key


def cleanup(work):
    shutil.rmtree(work, ignore_errors=True)
