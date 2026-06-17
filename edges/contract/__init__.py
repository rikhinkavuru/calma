"""A2 -- contract drafting: the LLM proposes a Calma verify.yaml for a messy real repo; the engine's
deterministic regrade_committed re-derives every binding's grade FROM THE DATA; on disagreement a concrete
counterexample goes back to the model on a 3-call budget; a repo-shape library turns the counterexample
corpus into priors so repeated shapes draft in one shot.

AI proposes; the data disposes. A2 reaches the verdict ONLY through edges.common.engine.verify (a
subprocess) + engine.read_ledger. It imports draft_contract as a READ-ONLY library (allowed -- not in the
firewall's forbidden set verdict/ledger/compare/recompute/numeric). The drafter emits the contract schema
only -- never a verdict, never a binding grade; `independently-bound` is reachable exclusively via the
data check.
"""
