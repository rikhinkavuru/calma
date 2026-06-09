# Vendoring a live-data repo (the BTC pattern, generalized)

Most real repos fetch market/ML data at runtime, so they can't run under Calma's network-off isolation
(they land UNVERIFIABLE). `scripts/calma_vendor.py` turns that one-time blocker into a repeatable step:
record the repo's HTTP fetches once (with network), then replay them offline so the recompute is
hermetic. (This is exactly what was done by hand for the BTC fixture — fetch Coinbase once, snapshot,
run offline.)

## Recipe

1. **Clone** the repo and note its entrypoint + the headline metric it claims.
2. **Record** (once, with network) — wrap the entrypoint:
   ```python
   import calma_vendor as v; v.install_record(".calma_httpcache")
   import runpy; runpy.run_path("main.py", run_name="__main__")
   ```
   Every `requests.get/post` and `urllib` fetch is cached under `.calma_httpcache/`, keyed by URL.
3. **Replay** (offline, under Calma isolation) — `v.install_replay(".calma_httpcache")` then run the
   entrypoint with network OFF. Cached URLs are served from disk; a **cache MISS raises**, so an offline
   replay is *provably* hermetic (it cannot silently reach the network).
4. **Emit gate** — if the repo only prints its number (no CSV/JSON/parquet), add a one-line emit of the
   raw series/predictions so `recompute.py` has a machine-readable artifact to recompute from. This is
   the only remaining per-repo step; everything else is mechanical.
5. Point a `verify.yaml` at the emitted artifact + the claimed metric and run `calma verify`.

## Status

The shim is tested (record → replay → miss, `tests/test_vendor.py`). The per-repo emit step (#4) is
inherent: a repo that never writes a machine-readable output must have one added before its headline
number can be independently recomputed. With the shim, growing the real-repo corpus is now bounded,
documented work rather than a blocker — each newly-vendored repo tightens the served-fraction / PPV.
