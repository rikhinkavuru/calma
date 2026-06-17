"""calma.app - the HOSTED GitHub App variant of the PR bot (B4). For the hosted product (not the
self-hosted-in-CI path): a central webhook receiver runs Calma on CALMA's infra, posts as a distinct
app identity, and can CREATE CHECK-RUNS (App-only). The customer installs the App; their PR code is
fetched and re-executed in CALMA's network-off sandbox, so the LLM/signing keys never touch the
customer repo.

Transport only, exactly like pr/ and mcp/: every verdict comes from the engine. app/ imports the pr/
transport (which shells to the engine) and never the verdict core (app/tests/test_firewall.py). The
webhook REJECTS a bad/absent HMAC signature before doing any work.
"""
