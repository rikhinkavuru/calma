"""calma.pr - the PR-comment bot: Calma's deterministic verifier as a GitHub PR check.

The CodeRabbit-shaped sibling of the MCP server. AI proposes (the PR's numbers), determinism disposes
(the engine's verdict). This package is a TRANSPORT only: it shells out to the engine
(`python -m edges.extract` and `calma.py verify --json`) and maps the engine's findings -> GitHub
review comments + a check-run. It NEVER imports verdict/ledger/compare/recompute/numeric and never
computes or paraphrases a verdict (see pr/tests/test_firewall.py).

Two halves, kept split for the pwn-request-proof security model (GitHub Security Lab):
  - UNPRIVILEGED (B1): diff -> verify targets -> a findings bundle. Runs untrusted PR code ONLY inside
    the engine's network-off sandbox; holds no secrets, read-only token. pr/run_pr.py.
  - PRIVILEGED (B2): consume the bundle (as UNTRUSTED DATA) -> a batched inline review + a gating
    check-run. The only code that holds a write token. pr/comment_pr.py.
"""
