"""runner.secrets — per-tenant secret store for the data-acquisition phase (four-unlocks plan §8).

Data-behind-auth repos (a gated HuggingFace dataset, an S3 bucket, a Kaggle competition) need a credential to
download. This module holds those per tenant and injects them **into the acquire sandbox only** — never the
eval run — so the recompute stays credential-free and FCR holds (a leaked/absent token → a failed acquire →
DISCOVERED, never a false CONFIRM).

Security posture (v1, honest about its limits):
  * Values are process-memory only (single-instance MVP, same as the Limiter / INSTALLATIONS store); the durable
    encrypted store is the control plane later. The API returns NAMES + metadata, never values.
  * The gold standard (Deno Sandbox / opencomputer / iron-proxy) never lets the VM see the raw token — a proxy
    swaps a placeholder at the network layer. That's a separate subsystem; here the acquire code DOES see the
    token in its env, so two mitigations make that safe: (1) short-lived, fine-grained, read-scoped tokens, and
    (2) an egress allowlist (runner.egress) so a leaked token can only reach the data host, not an attacker.
  * `redact` scrubs any secret value out of a log line before it is stored.

The owner (local operator) tenant is seeded from the host env (HF_TOKEN, KAGGLE_KEY, AWS_*) so a local
acquire works with the operator's own keys with zero setup.
"""
from __future__ import annotations

import os
import threading

# Recognised data-credential env names → the egress hosts that credential is scoped to. Injecting a secret also
# widens the acquire allowlist to exactly these hosts (runner.egress.allowlist_for), never the whole internet.
KNOWN_SECRETS: dict[str, tuple[str, ...]] = {
    "HF_TOKEN": ("huggingface.co", "*.hf.co", "cdn-lfs.huggingface.co", "*.huggingface.co"),
    "HUGGING_FACE_HUB_TOKEN": ("huggingface.co", "*.hf.co", "cdn-lfs.huggingface.co", "*.huggingface.co"),
    "KAGGLE_KEY": ("kaggle.com", "*.kaggle.com", "storage.googleapis.com"),
    "KAGGLE_USERNAME": ("kaggle.com", "*.kaggle.com"),
    "AWS_ACCESS_KEY_ID": ("*.amazonaws.com", "s3.amazonaws.com"),
    "AWS_SECRET_ACCESS_KEY": ("*.amazonaws.com", "s3.amazonaws.com"),
    "GOOGLE_APPLICATION_CREDENTIALS": ("*.googleapis.com", "storage.googleapis.com"),
    "WANDB_API_KEY": ("api.wandb.ai", "*.wandb.ai"),
    "GITHUB_TOKEN": ("github.com", "*.githubusercontent.com", "codeload.github.com"),
}
# env-name prefixes/whole-names also accepted (a tenant may store an org-specific token name).
_HOST_ENV_SEED = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "KAGGLE_KEY", "KAGGLE_USERNAME",
                  "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "WANDB_API_KEY")


def _valid_name(name: str) -> bool:
    """A conservative env-var name (prevents a malformed/injected key from reaching the sandbox env)."""
    import re
    return isinstance(name, str) and bool(re.match(r"^[A-Z_][A-Z0-9_]{0,63}$", name))


class SecretStore:
    """Per-tenant secret bag. Thread-safe; values never leave via `names`/`usage` (only `env_for` returns them,
    and only the trusted in-process runner calls that)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, str]] = {}     # tenant -> {NAME: value}

    def set_secret(self, tenant: str, name: str, value: str) -> bool:
        if not tenant or not _valid_name(name) or not isinstance(value, str) or not value:
            return False
        with self._lock:
            self._store.setdefault(tenant, {})[name] = value
        return True

    def delete_secret(self, tenant: str, name: str) -> None:
        with self._lock:
            self._store.get(tenant, {}).pop(name, None)

    def names(self, tenant: str) -> list[str]:
        """The secret NAMES a tenant has stored — never the values (safe to show in a UI / log)."""
        with self._lock:
            return sorted(self._store.get(tenant, {}).keys())

    def env_for(self, tenant: str) -> dict[str, str]:
        """The {NAME: value} env to inject into an ACQUIRE phase for this tenant. Callers MUST use this only on
        the network-enabled acquire step, never the eval run (FCR + least-exposure)."""
        with self._lock:
            return dict(self._store.get(tenant, {}))

    def values(self, tenant: str) -> list[str]:
        """The raw values (for redaction only)."""
        with self._lock:
            return [v for v in self._store.get(tenant, {}).values() if v]

    def redact(self, text: str, tenant: str) -> str:
        """Scrub every stored secret value for `tenant` out of a string before it is logged."""
        if not text:
            return text
        for v in self.values(tenant):
            if v and len(v) >= 6:
                text = text.replace(v, "***")
        return text

    def seed_owner_from_env(self, tenant: str = "owner") -> None:
        """Seed the local operator's tenant from the host env so a local acquire works with their own keys."""
        for name in _HOST_ENV_SEED:
            v = os.environ.get(name)
            if v:
                self.set_secret(tenant, name, v)


_STORE: SecretStore | None = None


def get_store() -> SecretStore:
    """Process-wide singleton secret store (mirrors core.limits.get_limiter)."""
    global _STORE
    if _STORE is None:
        _STORE = SecretStore()
        _STORE.seed_owner_from_env()
    return _STORE
