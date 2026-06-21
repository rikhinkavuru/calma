"""L2: a writer's --out is contained - no parent/traversal escape (only out != source was guarded
before). L3: the evidence bundle declares it is NOT a redacted public registry entry, and the
registry's redaction whitelist (which the evidence bundle deliberately is not) stays intact.
Pure stdlib, offline. Run: python3 test_out_containment.py
"""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import pathsafe as PS  # noqa: E402
import registry_site as RS  # noqa: E402
import registry as REG  # noqa: E402
import evidence_bundle as EV  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


tmp = tempfile.mkdtemp(prefix="calma_l2_")
src = os.path.join(tmp, "proj", "reg")
os.makedirs(src)

# --- L2: guard_out_dir blocks out==source and parent-traversal (ancestor); allows arbitrary else ---
truth(PS.guard_out_dir(os.path.join(src, "site"), src).endswith("site"),
      "guard_out_dir: the default in-source subdir is allowed")
for bad, why in [(src, "out == source"),
                 (os.path.dirname(src), "out is the source's parent (ancestor)"),
                 (os.path.join(src, ".."), "out is an ancestor via .. traversal")]:
    try:
        PS.guard_out_dir(bad, src)
        truth(False, "guard_out_dir must reject (%s): %r" % (why, bad))
    except ValueError:
        truth(True, "guard_out_dir rejects %s" % why)
# an arbitrary sibling / separate dir is allowed (the writers may deposit a pack anywhere)
truth(PS.guard_out_dir(os.path.join(tmp, "proj", "site_out"), src).endswith("site_out"),
      "guard_out_dir: a sibling dir is allowed")
truth(PS.guard_out_dir(os.path.join(tmp, "elsewhere"), src).endswith("elsewhere"),
      "guard_out_dir: an arbitrary separate dir is allowed (intended use)")

# --- L2: build_site refuses a parent-traversal --out (after the HEAD gate) ---
open(os.path.join(src, "HEAD.json"), "w").write("{}")
try:
    RS.build_site(src, os.path.join(src, ".."))   # the source's parent (ancestor)
    truth(False, "build_site must refuse an ancestor --out")
except ValueError:
    truth(True, "build_site refuses an ancestor/parent-traversal --out")

# --- L3: the evidence bundle declares its non-redaction, and names the registry contrast ---
truth("NOT" in EV.REDACTION_NOTICE and "registry" in EV.REDACTION_NOTICE.lower(),
      "L3: REDACTION_NOTICE says it is NOT a redacted registry entry")
truth("lineage" in EV.REDACTION_NOTICE.lower(),
      "L3: REDACTION_NOTICE names the input-lineage exposure")
# HERE=tests; ../../../../.. = repo root (tests->scripts->calma->skills->.claude->root)
doc = os.path.join(HERE, "..", "..", "..", "..", "..", "docs", "internal", "EVIDENCE-VS-REGISTRY.md")
truth(os.path.isfile(doc), "L3: docs/internal/EVIDENCE-VS-REGISTRY.md exists")

# --- L3: the registry redaction whitelist (the thing evidence is NOT) is intact ---
truth("path" not in REG.ALLOWED_FIELDS and "uri" not in REG.ALLOWED_FIELDS
      and "input_lineage" not in REG.ALLOWED_FIELDS,
      "L3: registry ALLOWED_FIELDS excludes paths/uris/lineage (structural redaction)")
truth("verdict" in REG.ALLOWED_FIELDS and "claimed" in REG.ALLOWED_FIELDS,
      "L3: registry ALLOWED_FIELDS still carries the verdict scalars")

shutil.rmtree(tmp, ignore_errors=True)
print("out-containment (L2/L3): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
