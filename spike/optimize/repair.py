#!/usr/bin/env python
"""optimize.repair — feature 1 meta-eval: the repair loop raises coverage without ever moving FCR.

The loop's whole FCR argument is STRUCTURAL — an env-only action space plus a source-modified cap — so this
instrument proves the structure rather than sampling repos: (1) no source-edit action exists; (2) an injected
out-of-enum action is refused; (3) the source-modified cap is downgrade-only (a CONFIRMED → REPRODUCED-ONLY,
a REFUTED untouched, never an upgrade). If all three hold, the loop can only turn DISCOVERED into a real
verdict — it can never manufacture a confirm.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import verdict as VD  # noqa: E402
from runner import repair as R  # noqa: E402
import pipeline as P  # noqa: E402


def measure():
    no_source_edit = not ({"SOURCE_EDIT", "EDIT", "WRITE", "PATCH"} & R.ACTIONS)

    def evil(result, history):
        return {"type": "SOURCE_EDIT", "arg": "metric.py"}
    _r, man = R.repair_loop(lambda a: {"ran_ok": False, "meta": [{"stderr_tail": "boom"}]},
                            evil, lambda a: True, max_steps=4)
    injection_refused = bool(man["gave_up"] and not man["steps"])

    conf = {"verdict": VD.CONFIRMED, "validity": {"invalidating": [], "advisory": []}}
    ref = {"verdict": VD.REFUTED, "validity": {"invalidating": [], "advisory": []}}
    P._apply_agent_modified_cap([conf, ref], ["metric.py"])
    cap_downgrade_only = (conf["verdict"] == VD.REPRODUCED_ONLY and ref["verdict"] == VD.REFUTED)

    fcr_safe = no_source_edit and injection_refused and cap_downgrade_only
    return {"no_source_edit": no_source_edit, "injection_refused": injection_refused,
            "cap_downgrade_only": cap_downgrade_only, "fcr_safe": fcr_safe,
            "false_confirm_rate": 0.0 if fcr_safe else 1.0}


def main():
    m = measure()
    with open(os.path.join(HERE, "repair_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== REPAIR LOOP (feature 1) ===")
    print("env-only=%s  injection-refused=%s  cap-downgrade-only=%s  FCR-safe=%s"
          % (m["no_source_edit"], m["injection_refused"], m["cap_downgrade_only"], m["fcr_safe"]))
    return 0 if m["fcr_safe"] else 1


if __name__ == "__main__":
    sys.exit(main())
