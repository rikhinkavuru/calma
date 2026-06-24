"""End-to-end test of the verifications API against the REAL stack (Supabase + R2 + the engine).
Bootstraps a throwaway org/tenant/key, uploads a real benchmark case as a bundle, submits it through the
API, and asserts the engine's verdict came back and persisted. Cleans up the org (cascade) at the end.

Run:  ~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_e2e
"""
from __future__ import annotations

import hashlib
import io
import os
import secrets
import sys
import tarfile

from fastapi.testclient import TestClient

from control_plane.api import bootstrap, config, repo, storage
from control_plane.api.app import app

CASE = os.path.join(config.REPO_ROOT, "benchmark", "cases", "win_b")

_n = _fail = 0


def ok(cond, label):
    global _n, _fail
    _n += 1
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        _fail += 1


def make_bundle_tar(case_dir) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in sorted(os.listdir(case_dir)):
            tf.add(os.path.join(case_dir, name), arcname=name)
    return buf.getvalue()


def main():
    client = TestClient(app)

    # health
    ok(client.get("/healthz").json().get("ok") is True, "healthz reports db reachable")

    # bootstrap a throwaway tenant + key
    slug = "e2e-" + secrets.token_hex(3)
    bs = bootstrap.init("E2E Test Org", slug, "e2e@example.com", "test")
    org_id, tenant_id, token = bs["org_id"], bs["tenant_id"], bs["token"]
    H = {"Authorization": "Bearer " + token}

    # auth negative controls
    ok(client.get("/v1/verifications").status_code == 401, "no key -> 401")
    ok(client.get("/v1/verifications", headers={"Authorization": "Bearer calma_sk_test_dead_beef"}
                  ).status_code == 401, "bad key -> 401")

    # upload a real case as a bundle (simulate the client's presigned PUT with a direct put)
    tar = make_bundle_tar(CASE)
    sha = hashlib.sha256(tar).hexdigest()
    bundle_key = storage.tenant_key(tenant_id, "bundles", sha + ".tar.gz")
    storage.put_bytes(bundle_key, tar, "application/gzip")
    ok(storage.exists(bundle_key), "bundle uploaded to R2")

    # presigned-upload endpoint smoke
    up = client.post("/v1/uploads", headers=H, json={"kind": "bundle", "sha256": sha}).json()
    ok(up.get("url", "").startswith("http") and up.get("uri"), "POST /v1/uploads returns a presigned URL")

    # submit
    body = {
        "recipe_id": "trading.total_return", "recipe_version": "1.0.0", "template_id": "python-3.11",
        "trust": "own-code",
        "claim": {"metric": "total_return", "value": 0.0077},
        "bundle": {"uri": bundle_key, "sha256": sha, "entrypoint": "gen.py", "language": "python"},
    }
    r = client.post("/v1/verifications", headers=H, json=body)
    ok(r.status_code == 200, "submit -> 200 (got %s)" % r.status_code)
    j = r.json()
    vid = j.get("verification_id")
    print("  -- verification_id=%s status=%s verdict=%s recomputed=%s tier=%s"
          % (vid, j.get("status"), j.get("verdict"),
             (j.get("recomputed") or {}).get("value"),
             (j.get("execution") or {}).get("isolation_tier")))
    ok(bool(vid), "response carries verification_id (not job_id)")
    ok("job_id" not in j and "run_id" not in j, "no internal job_id/run_id leaks into the payload")
    ok(j.get("status") == "COMPLETED", "status COMPLETED")
    ok(j.get("verdict") in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"), "verdict is a confirm tier")
    rec = (j.get("recomputed") or {}).get("value")
    ok(rec is not None and abs(rec - 0.0077) < 0.01, "recomputed total_return ~ 0.0077 (got %s)" % rec)
    ok((j.get("execution") or {}).get("tier_verified") is True, "tier_verified True (seatbelt on macOS)")

    # GET status + result
    ok(client.get("/v1/verifications/%s" % vid, headers=H).json().get("verdict") == j.get("verdict"),
       "GET /{id} returns the same verdict")
    res = client.get("/v1/verifications/%s/result" % vid, headers=H).json()
    ok(res.get("verification_id") == vid, "GET /{id}/result")

    # proof (the stored evidence bundle)
    pr = client.get("/v1/verifications/%s/proof" % vid, headers=H)
    ok(pr.status_code == 200 and pr.json().get("verification_id") == vid, "GET /{id}/proof serves evidence")

    # idempotency: same Idempotency-Key -> same verification, no re-run
    ik = secrets.token_hex(8)
    a = client.post("/v1/verifications", headers=dict(H, **{"Idempotency-Key": ik}), json=body).json()
    b = client.post("/v1/verifications", headers=dict(H, **{"Idempotency-Key": ik}), json=body).json()
    ok(a.get("verification_id") == b.get("verification_id"),
       "same Idempotency-Key -> same verification_id (no double-run)")

    # list + cross-tenant isolation (a fresh tenant sees none of these)
    lst = client.get("/v1/verifications?limit=5", headers=H).json()
    ok(len(lst.get("data", [])) >= 1, "list returns this tenant's verifications")
    other = bootstrap.init("Other Org", "e2e-" + secrets.token_hex(3), "x@example.com", "test")
    lst2 = client.get("/v1/verifications", headers={"Authorization": "Bearer " + other["token"]}).json()
    ok(lst2.get("data") == [], "a different tenant sees ZERO of this tenant's verifications (isolation)")

    # cleanup both orgs (cascade)
    conn = repo.connect()
    for oid in (org_id, other["org_id"]):
        conn.execute("DELETE FROM orgs WHERE id=%s", (oid,))
    conn.close()
    print("  -- cleaned up test orgs")

    print("\n%d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
