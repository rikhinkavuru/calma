"""runner.egress — build the outbound allowlist for the data-acquisition phase (four-unlocks plan §8).

The acquire phase is the one time a verify touches the network: it runs the repo's OWN download scripts so the
datasets materialise. Today that phase runs with the whole internet open. This module narrows it to a
default-deny allowlist so a prompt-injected acquire script (or a leaked credential) can only reach the data
hosts, not an attacker-controlled server.

E2B enforces this natively (Sandbox network `allow_out` / `deny_out`, domain filtering via SNI on 443 / Host on
80 — see the four-unlocks research). The posture we emit here is:

    deny_out = ['0.0.0.0/0']        # default-deny everything
    allow_out = [<data hosts>]      # then re-open exactly the hosts the credentials are scoped to

Pure + stdlib — the transport (e2b_runner) applies it; this just computes it, so it's unit-testable.
"""
from __future__ import annotations

from . import secrets as SECRETS

# Common public data/model hosts a research repo's acquire step legitimately reaches, even with NO credential
# (Zenodo DOIs, figshare, OSF, raw GitHub, the PyPI/conda index a mid-acquire pip needs). Kept tight.
BASE_DATA_HOSTS: tuple[str, ...] = (
    "huggingface.co", "*.hf.co", "*.huggingface.co", "cdn-lfs.huggingface.co",
    "zenodo.org", "*.zenodo.org",
    "figshare.com", "*.figshare.com",
    "osf.io", "*.osf.io",
    "github.com", "*.githubusercontent.com", "codeload.github.com",
    "*.amazonaws.com", "storage.googleapis.com", "*.googleapis.com",
    "pypi.org", "files.pythonhosted.org",                     # a pip called mid-acquire
    "conda.anaconda.org", "repo.anaconda.com",                # a conda/micromamba solve mid-acquire
)

DENY_ALL = ("0.0.0.0/0",)


def allowlist_for(secret_names, extra_hosts=None) -> list[str]:
    """The `allow_out` host list for an acquire phase: the base data hosts, widened by exactly the hosts each
    stored credential is scoped to (runner.secrets.KNOWN_SECRETS), plus any caller-provided extras. De-duped,
    order-stable. Empty `secret_names` still returns the base list (public data still needs egress)."""
    hosts: list[str] = list(BASE_DATA_HOSTS)
    for name in secret_names or []:
        for h in SECRETS.KNOWN_SECRETS.get(name, ()):  # a credential widens egress to its own hosts only
            hosts.append(h)
    for h in extra_hosts or []:
        if isinstance(h, str) and h:
            hosts.append(h)
    out, seen = [], set()
    for h in hosts:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def acquire_network(secret_names=None, extra_hosts=None) -> dict:
    """The full network posture for an acquire phase: default-deny + the data-host allowlist. The transport
    passes `allow_out`/`deny_out` to the sandbox. Returns a plain dict so it's trivially serialisable/testable."""
    return {"allow_out": allowlist_for(secret_names, extra_hosts), "deny_out": list(DENY_ALL)}
