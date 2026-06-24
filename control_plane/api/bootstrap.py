"""control_plane.api.bootstrap — admin CLI to create an org/tenant/user/api-key and seed the minimal
registry (a template + a few recipes) so submits FK-resolve. The plaintext API key is printed ONCE.

    ~/.calma/cp-venv/bin/python -m control_plane.api.bootstrap init --org "Acme" --slug acme --env test
"""
from __future__ import annotations

import argparse
import sys

from . import keys, repo
from .repo import _one

# minimal registry seed (the engine recomputes from the bundle's contract; these rows are the API's
# registry guard / billing anchor). Real registry sync from the engine's recipe catalogue is a follow-up.
_TEMPLATES = [("python-3.11", "python", "sha256:base", "local-docker"),
              ("base", "python", "sha256:e2b-base", "e2b")]
_RECIPES = [("trading.total_return", "1.0.0", "trading", "total_return"),
            ("trading.sharpe", "1.0.0", "trading", "sharpe"),
            ("analytics.row_count", "1.0.0", "analytics", "row_count")]


def seed_registry(conn):
    for tid, lang, digest, prov in _TEMPLATES:
        conn.execute("INSERT INTO templates (id, language, image_digest, provider) "
                     "VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING", (tid, lang, digest, prov))
    for rid, ver, fam, metric in _RECIPES:
        conn.execute("INSERT INTO recipes (id, version, family, metric, spec_sha256) "
                     "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id, version) DO NOTHING",
                     (rid, ver, fam, metric, b"\x00" * 32))


def init(org_name, slug, email, env):
    conn = repo.connect()
    org = _one(conn, "INSERT INTO orgs (name) VALUES (%s) RETURNING id", (org_name,))
    tenant = _one(conn, "INSERT INTO tenants (org_id, slug, object_bucket) VALUES (%s,%s,%s) "
                        "RETURNING id", (org["id"], slug, "calma"))
    user = _one(conn, "INSERT INTO users (org_id, email) VALUES (%s,%s) RETURNING id",
                (org["id"], email))
    conn.execute("INSERT INTO memberships (org_id, user_id, role) VALUES (%s,%s,'owner')",
                 (org["id"], user["id"]))
    k = keys.generate(env)
    conn.execute("INSERT INTO api_keys (tenant_id, prefix, key_id, key_hash, environment) "
                 "VALUES (%s,%s,%s,%s,%s)",
                 (tenant["id"], k["prefix"], k["key_id"], k["key_hash"], k["environment"]))
    seed_registry(conn)
    conn.close()
    print("org_id    :", org["id"])
    print("tenant_id :", tenant["id"])
    print("API key   :", k["token"], "   <-- shown ONCE; store it now")
    return {"org_id": str(org["id"]), "tenant_id": str(tenant["id"]), "token": k["token"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--org", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--email", default="owner@example.com")
    p.add_argument("--env", default="test", choices=["live", "test"])
    sub.add_parser("seed")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        init(a.org, a.slug, a.email, a.env)
    elif a.cmd == "seed":
        conn = repo.connect()
        seed_registry(conn)
        conn.close()
        print("registry seeded")


if __name__ == "__main__":
    sys.exit(main())
