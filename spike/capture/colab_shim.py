"""colab_shim — a defensive stand-in for `google.colab`, installed at interpreter startup (via sitecustomize)
whenever the REAL google.colab is absent (i.e. anywhere that isn't Google Colab).

A large share of real notebook repos are exported straight from Colab and open with
`from google.colab import files; uploaded = files.upload()` or `drive.mount(...)`. Outside Colab that import
raises ModuleNotFoundError and the whole notebook dies on cell 1 — nothing runs, nothing binds. The shim
makes those calls succeed against the repo's OWN committed data: `files.upload()` returns every committed
data file in the cwd as {name: bytes} (exactly what a Colab notebook expects to receive), and `drive.mount()`
is a no-op. This unblocks reproduction for a whole class of the market without touching the repo's compute —
a wrong/empty result still fails closed to DISCOVERED, never a false verdict.

Fail-soft: any error installing the shim is swallowed; a real google package is preserved (we graft `.colab`
onto it rather than replacing it), so genuine google-api imports keep working.
"""
from __future__ import annotations

import os
import sys
import types

# data files a Colab notebook typically uploads — bounded per-file so a giant CSV can't blow memory
_DATA_EXTS = (".csv", ".tsv", ".json", ".xlsx", ".xls", ".txt", ".data", ".parquet", ".pkl", ".npy", ".npz")
_MAX_FILE = 200 * 1024 * 1024


def _committed_data(cwd: str) -> dict:
    out: dict = {}
    try:
        for fn in sorted(os.listdir(cwd)):
            p = os.path.join(cwd, fn)
            if not (os.path.isfile(p) and fn.lower().endswith(_DATA_EXTS)):
                continue
            try:
                if os.path.getsize(p) > _MAX_FILE:
                    continue
                with open(p, "rb") as fh:
                    out[fn] = fh.read()
            except OSError:
                continue
    except OSError:
        pass
    return out


def install() -> None:
    try:
        import google.colab  # noqa: F401 — real Colab: do nothing
        return
    except Exception:  # noqa: BLE001 — not in Colab (the common case) → install the shim
        pass
    try:
        colab = types.ModuleType("google.colab")

        files_mod = types.ModuleType("google.colab.files")
        # types.ModuleType has no statically-declared attributes; set them via setattr — the correct typed
        # idiom for building a module dynamically (a bare `mod.attr = …` trips mypy's [attr-defined]).
        setattr(files_mod, "upload", lambda *a, **k: _committed_data(os.getcwd()))   # the repo's committed data
        setattr(files_mod, "download", lambda *a, **k: None)
        setattr(files_mod, "view", lambda *a, **k: None)

        drive_mod = types.ModuleType("google.colab.drive")

        def _mount(mountpoint="/content/drive", **k):
            try:
                os.makedirs(mountpoint, exist_ok=True)
            except OSError:
                pass
        setattr(drive_mod, "mount", _mount)
        setattr(drive_mod, "flush_and_unmount", lambda *a, **k: None)

        output_mod = types.ModuleType("google.colab.output")
        userdata_mod = types.ModuleType("google.colab.userdata")
        setattr(userdata_mod, "get", lambda *a, **k: os.environ.get(a[0]) if a else None)

        setattr(colab, "files", files_mod)
        setattr(colab, "drive", drive_mod)
        setattr(colab, "output", output_mod)
        setattr(colab, "userdata", userdata_mod)

        # preserve a real `google` namespace package if one exists; only fabricate it when absent
        try:
            google_pkg = __import__("google")
        except Exception:  # noqa: BLE001
            google_pkg = types.ModuleType("google")
            google_pkg.__path__ = []          # mark as a package
            sys.modules["google"] = google_pkg
        setattr(google_pkg, "colab", colab)

        sys.modules["google.colab"] = colab
        sys.modules["google.colab.files"] = files_mod
        sys.modules["google.colab.drive"] = drive_mod
        sys.modules["google.colab.output"] = output_mod
        sys.modules["google.colab.userdata"] = userdata_mod
    except Exception:  # noqa: BLE001 — instrumentation must never break the interpreter
        pass
