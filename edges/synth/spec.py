"""What a human (or the fleet harness) hands the synthesizer. The oracle is NAMED, not implemented:
the gate executes it in the reference venv, so the spec author only states which published callable is
ground truth, its argument tags, and any kwargs (e.g. ddof=1)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Spec:
    metric_id: str                 # ^[a-z][a-z0-9_]*$  (the loop asserts this before any LLM call)
    family: str                    # one of the draft-schema family enum values
    description: str               # one plain-language sentence of what it measures (<=300 chars)
    oracle_call: str               # e.g. "scipy.stats.sem" (must match the oracle.call regex / allowlist)
    oracle_args: list              # input tags in call order, e.g. ["value"]
    oracle_kwargs: dict = field(default_factory=dict)   # e.g. {"ddof": 1}
    inputs_hint: dict = field(default_factory=dict)     # optional tag -> "list"|"rawlist" hint for the model
    aliases_seed: list = field(default_factory=list)    # optional human paraphrases to seed enrichment
    claim_hint_seed: list = field(default_factory=list)  # optional spoken-name phrases for claim routing
