# Install & run — from zero to a verdict in under 15 minutes

Calma's core is **pure Python stdlib** (`dependencies = []`), so every path below is fast and offline. Pick one.

## 1. pip (library + CLI)

```bash
pip install calma                 # the verifier + the `calma` command
pip install 'calma[parquet]'      # + the optional columnar adapter for Numerai/Crunch .parquet
```

Then either drive the CLI:

```bash
calma demo                        # watch a real inflated backtest get caught (~5s, no setup)
calma init numerai                # drop a starter verify.yaml tuned to your stack
calma verify ./my-result "Sharpe 1.8"
```

…or call it **in-process** as a library (the same deterministic core the CLI uses):

```python
from calma import verify, recompute, draft

result = verify("./my-result", "Sharpe 1.8")     # -> the full verdict dict
metrics = recompute("./my-result/verify.yaml")    # -> recompute the headline number only
```

`calma.__version__` tracks the engine's version (single source of truth — the library and CLI can never drift).

## 2. The Claude skill / hook (zero-install, zero-touch)

If you use Claude Code, Cursor, or Codex, Calma runs as a **Stop hook / MCP tool** — it auto-verifies the numbers your agent computes *before you see them*, with nothing to install. See the [README](../README.md) and [PR-bot guide](pr-bot.md).

## 3. Local symlink (no pip, no venv)

```bash
make install                      # symlinks `calma` onto your PATH (pure stdlib, no deps)
calma demo
```

## 4. Docker (non-root, network-off)

```bash
docker build -t calma:latest .
docker run --rm --network=none -v "$PWD:/work" -w /work calma:latest verify . "Sharpe 1.8"
```

The image is **multi-stage and non-root** (the verifier re-executes untrusted code, so it never needs root). Build the parquet variant with `--build-arg EXTRAS=parquet`.

---

## The <15-minute path, concretely

1. `pip install calma` — **~30s**.
2. `calma demo` — see a `+14,698%` backtest get **REFUTED** to its real number — **~5s**.
3. `calma init <your framework>` (`numerai` · `crunchdao` · `sklearn` · `xgboost` · `pytorch` · `backtrader` · `vectorbt` · `zipline`) — a runnable starter contract with fill-in `_note` instructions — **~1 min**.
4. Point its 2–3 paths at your real outputs, add a validity block if you have one (`split`, `trials`, `frictions`, `embargo`, `simulation_assumptions`), and `calma verify . "<your claim>"` — **a verdict in minutes**.

Every verdict carries a one-command **`replay`** anyone can run to re-derive it offline, byte-for-byte.

---

## Supply chain (the release pipeline)

Because the core is dependency-free, the supply chain is **one pinned line** — `pyarrow`, only in the `parquet` extra. The release pipeline (CI) should:

- publish to PyPI via **trusted publishing** (GitHub OIDC, no stored token);
- build the Docker image from a **digest-pinned** base, deps from a **hashed lock** (`--require-hashes`, fails closed);
- attach a **cosign keyless signature + a CycloneDX/SPDX SBOM + SLSA provenance**, verifiable with `gh attestation verify`.

The `calma-package` CI workflow already builds the wheel, installs it in a clean venv, and asserts the **firewall** (the installed core imports zero third-party) on every push — so what a customer `pip install`s is continuously verified.
