"""calma - a thin library facade over the pure-stdlib verification engine.

`from calma import verify` runs the SAME deterministic core the CLI / Claude skill / PR-bot use - this
package is a thin CLIENT of the one engine (library-first), never a second implementation. The engine
modules live at calma/_engine/ in the installed wheel, and at .claude/skills/calma/scripts/ in the source
tree (editable install); we locate that dir, add it to sys.path, and re-export the public API.

The engine's top-level CLI module is itself named `calma.py`, which would collide with THIS package, so it
is loaded via importlib under a private name (`_calma_engine`); the other engine modules (recompute,
draft_contract, ...) have non-colliding names and import normally off sys.path.

Public API:
    verify(target, claim=None, metric=None, run_id="run", opts=None) -> dict   # the verdict
    recompute(contract_path, base=None, k=3) -> dict                            # recompute metrics only
    draft(target, **kw) -> dict                                                 # draft a verify.yaml
    load_contract(path) / validate_contract(contract)
    __version__
"""
import importlib.util
import os
import sys

__all__ = ["verify", "recompute", "draft", "load_contract", "validate_contract", "engine_dir", "__version__"]


def engine_dir():
    """Locate the pure-stdlib engine scripts dir: the bundled calma/_engine/ (installed wheel) or the
    .claude/skills/calma/scripts/ source tree (editable install / running from the repo)."""
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "_engine")
    if os.path.isfile(os.path.join(bundled, "calma.py")):
        return bundled
    root = here
    for _ in range(8):  # walk up to the repo root
        cand = os.path.join(root, ".claude", "skills", "calma", "scripts")
        if os.path.isfile(os.path.join(cand, "calma.py")):
            return cand
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent
    raise ImportError("calma engine not found (expected calma/_engine/calma.py in the wheel, or "
                      ".claude/skills/calma/scripts/calma.py in the source tree)")


_ENGINE = engine_dir()
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

# load the engine CLI module (calma.py) under a private name to avoid colliding with THIS package
if "_calma_engine" in sys.modules:
    _engine = sys.modules["_calma_engine"]
else:
    _spec = importlib.util.spec_from_file_location("_calma_engine", os.path.join(_ENGINE, "calma.py"))
    _engine = importlib.util.module_from_spec(_spec)
    sys.modules["_calma_engine"] = _engine
    _spec.loader.exec_module(_engine)

import draft_contract as _draft  # noqa: E402  (non-colliding engine module, off sys.path)
import recompute as _recompute  # noqa: E402

__version__ = _engine.__version__
verify = _engine.verify
recompute = _recompute.recompute_contract
load_contract = _draft.load_contract
validate_contract = _draft.validate_contract


def draft(target, **kw):
    """Draft (or AI-draft) a verify.yaml contract for `target` - a thin wrapper over the engine drafter."""
    return _engine.draft_cmd(target, **kw)
