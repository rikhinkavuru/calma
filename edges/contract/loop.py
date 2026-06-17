"""P2.2 -- the regrade counterexample loop (the teeth: data disposes, on a 3-call budget).

draft -> WRITE <target>/verify.yaml -> engine.verify (regrade_committed re-derives every binding's grade
FROM THE DATA) -> for each binding the data graded weaker than intended (or any metric inconclusive for a
binding reason) construct a CONCRETE counterexample from the actual column values -> feed it back ->
re-draft -> repeat to budget. Stops early when there are no disagreements. The model never sets a grade;
independently-bound is reachable only via the data check. A wrong draft costs iterations, never a false
verdict -- if unresolved after budget, the engine honestly reports inconclusive WITH the reason.

A2 reaches the verdict ONLY via engine.verify (subprocess) + engine.read_ledger. The data-derived grade
lives in ledger.json -> claims[].input_binding_status, NEVER in --json."""
import json
import os

from edges.common import engine, llm, store
from edges.contract.counterexample import (build_counterexample, column_evidence, disagreements,
                                           feedback_block)
from edges.contract.draft import (SYSTEM_PROMPT, _sanitize, assemble_inputs, llm_draft, _render_user)
from edges.contract.repo_scan import fingerprint
from edges.contract.schema import CONTRACT_SCHEMA

CE_LOG = os.path.join(os.path.dirname(__file__), "data", "counterexamples.jsonl")

_REDRAFT_HEADER = (
    "The deterministic data check re-derived every binding from the ACTUAL column values and DISAGREED "
    "with your draft on the bindings below. Each item shows the real numbers. Re-draft the contract, "
    "correcting ONLY these bindings (keep everything the check accepted). You earn \"independently-bound\" "
    "by pointing each binding at the column whose VALUES fit the role -- you cannot assert it.\n")


def _write_contract(repo_path, contract):
    """Write the committed verify.yaml (JSON is valid YAML; load_contract reads JSON first)."""
    with open(os.path.join(repo_path, "verify.yaml"), "w") as fh:
        json.dump(contract, fh, indent=2)


def draft_with_repair(repo_path, *, budget=3, model=None, extra_rules=(), seed_skeleton=None,
                      ce_log=None, drafts_log=None, ts=None):
    """Returns (final_contract, trace). Writes <repo_path>/verify.yaml each round, runs engine.verify,
    reads the ledger, computes disagreements, persists each counterexample, re-drafts with the feedback
    appended, to `budget` model calls total."""
    ce_log = ce_log or CE_LOG
    trace = {"repo_path": repo_path, "budget": budget, "rounds": [], "resolved": False,
             "final_verdict": None, "iterations_used": 0}
    contract = llm_draft(repo_path, model=model, extra_rules=extra_rules, seed_skeleton=seed_skeleton,
                         drafts_log=drafts_log, ts=ts)
    for i in range(1, budget + 1):
        trace["iterations_used"] = i
        _write_contract(repo_path, contract)
        res = engine.verify(repo_path)                       # regrade_committed fires (committed verify.yaml)
        led = engine.read_ledger(res["run_dir"])             # input_binding_status lives HERE
        diss = disagreements(contract, led, res)
        ces = []
        for d in diss:
            ev = column_evidence(repo_path, d["artifact"], d["column"], d["tag"])
            ce = build_counterexample(d, ev)
            ces.append(ce)
            rec = {"repo_fingerprint": fingerprint(repo_path), "round": i, **ce}
            if ts is not None:
                rec["ts"] = int(ts)
            store.append(ce_log, rec)
        trace["rounds"].append({"i": i, "contract": contract, "json_result": res,
                                "ledger_claims": led.get("claims", []),
                                "disagreements": diss, "counterexamples": ces})
        trace["final_verdict"] = res.get("verdict")
        if not diss:
            trace["resolved"] = True
            break
        if i == budget:
            break                                            # out of budget; engine reports honestly
        # re-draft with the counterexamples appended
        inputs = assemble_inputs(repo_path)
        system = SYSTEM_PROMPT
        if extra_rules:
            system = system + "\n\nLearned binding rules (apply these):\n" + \
                "\n".join("- " + r for r in extra_rules)
        user = _render_user(inputs, seed_skeleton=seed_skeleton,
                            redraft_block=_REDRAFT_HEADER + "\n" + feedback_block(ces) +
                            "\n\nRe-emit the full corrected contract via the `emit` tool. Do not change "
                            "metric_ids the check accepted; do not invent metrics; do not emit any grade.")
        raw = llm.structured(user, schema=CONTRACT_SCHEMA, model=model or llm.SONNET,
                             system=system, tool_name="emit")
        contract = _sanitize(raw, inputs)
    return contract, trace
