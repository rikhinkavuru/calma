"""sitecustomize — auto-imported by CPython at interpreter startup for any process whose PYTHONPATH
contains this directory. The runner prepends spike/capture to PYTHONPATH, so EVERY python the repo runs
(entrypoint + children) arms the capture hooks *before* the repo's own code imports sklearn — which is why
`from sklearn.metrics import accuracy_score` in the repo binds to our wrapped function.

It must be defensive: a broken sitecustomize would break every python in the sandbox. All real work is in
calma_capture.install_from_env(), itself fail-soft. No capture happens unless CALMA_CAPTURE_OUT is set.
"""
try:
    import calma_capture
    calma_capture.install_from_env()
except Exception:  # noqa: BLE001 — never let instrumentation break the interpreter
    pass

# Chain to a pre-existing sitecustomize the base image may ship (we prepend to PYTHONPATH, shadowing it).
try:  # pragma: no cover
    import importlib.util as _u
    import os as _os
    import sys as _sys
    _here = _os.path.dirname(_os.path.abspath(__file__))
    for _p in _sys.path:
        if not _p or _os.path.abspath(_p) == _here:
            continue
        _cand = _os.path.join(_p, "sitecustomize.py")
        if _os.path.isfile(_cand):
            _spec = _u.spec_from_file_location("_chained_sitecustomize", _cand)
            if _spec and _spec.loader:
                _mod = _u.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
            break
except Exception:  # noqa: BLE001
    pass
