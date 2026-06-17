"""The verify.yaml JSON Schema, as a Python dict -- the single source of truth for the structured() input
schema the drafter emits. binding_status and claim_confirmed are DELIBERATELY ABSENT: the model cannot
emit a grade; regrade_committed assigns binding_status from the data.

Authority on legality is draft_contract.validate_contract() + the vocabulary tables; this schema is a
superset-safe front gate and _sanitize() re-checks the out-of-vocab cases a schema can't range-check.
"""

CONTRACT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["run", "artifacts", "metrics"],
    "properties": {
        "run": {
            "type": "object", "additionalProperties": False, "required": ["entrypoint"],
            "properties": {
                "entrypoint": {"type": "string", "minLength": 1,
                               "description": "the command/script that re-produces the result, e.g. "
                                              "run.sh or main.py"},
                "network": {"type": "string", "enum": ["off", "on"], "default": "off"},
                "cwd": {"type": "string", "default": "."},
            },
        },
        "env": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "ecosystem": {"type": "string",
                              "enum": ["auto", "python-stdlib", "python", "r", "julia", "rust",
                                       "cpp", "node"]},
                "trust": {"type": "string", "enum": ["own-code", "untrusted-third-party"]},
            },
        },
        "artifacts": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "additionalProperties": False, "required": ["path", "columns"],
                "properties": {
                    "path": {"type": "string", "minLength": 1,
                             "description": "repo-relative path to a CSV the run emits/contains"},
                    "re_emit": {"type": "boolean",
                                "description": "true if the entrypoint regenerates this file"},
                    "columns": {
                        "type": "object", "minProperties": 1,
                        "additionalProperties": {
                            "type": "object", "additionalProperties": False,
                            "properties": {
                                "tag": {
                                    "type": ["string", "null"],
                                    "description": "semantic role; MUST be one of the engine's tags",
                                    "enum": [
                                        "return", "benchmark", "price", "value", "score", "prob",
                                        "prediction", "label", "target", "reference", "before", "after",
                                        "duration", "hits", "query", "relevance", "rank", "problem",
                                        "correct", "sample_a", "sample_b", "group", "outcome", "flag",
                                        "cashflow", "cost", "weight", "timestamp", "x", "y", "magnitude",
                                        "amount", "quantity", "left_key", "joined_key", None,
                                    ],
                                },
                                "dtype": {"type": "string", "enum": ["float", "int", "str", "bool"]},
                                "na_policy": {"type": "string", "enum": ["error", "drop", "zero"]},
                            },
                        },
                    },
                },
            },
        },
        "metrics": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["metric_id", "artifact", "binding"],
                "properties": {
                    "metric_id": {"type": "string", "minLength": 1,
                                  "description": "MUST be an engine metric_id; never invented"},
                    "artifact": {"type": "string", "minLength": 1,
                                 "description": "must equal one artifacts[].path"},
                    "binding": {
                        "type": "object", "minProperties": 1,
                        "additionalProperties": {"type": "string"},
                        "description": "map of required tag -> column name in `artifact`",
                    },
                    "convention": {"type": ["string", "null"],
                                   "description": "recompute convention string; null = recipe default"},
                    "claimed_value": {"type": ["number", "null"],
                                      "description": "the author's reported number, or null"},
                    "claimed_precision": {"type": ["number", "null"],
                                          "description": "leave null (engine fills via claim_precision)"},
                    "headline": {"type": "boolean",
                                 "description": "true for the single primary metric of the repo"},
                },
                # binding_status and claim_confirmed are DELIBERATELY ABSENT -- the model cannot grade.
            },
        },
        "baselines": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["metric_id", "artifact", "binding"],
                "properties": {
                    "metric_id": {"type": "string"}, "artifact": {"type": "string"},
                    "binding": {"type": "object", "additionalProperties": {"type": "string"}},
                    "label": {"type": "string", "description": "human label, e.g. buy-and-hold"},
                },
            },
        },
        "split": {
            "type": ["object", "null"], "additionalProperties": False,
            "description": "train/test split for the leakage family; null/absent => NOT-APPLICABLE",
            "properties": {
                "train": {"type": "string"}, "test": {"type": "string"},
                "file": {"type": "string"}, "column": {"type": "string"},
                "test_value": {"type": ["string", "number"]}, "embargo": {"type": ["string", "number"]},
            },
        },
        "keys": {
            "type": ["object", "null"], "additionalProperties": False,
            "properties": {"id": {"type": "string"}, "time": {"type": "string"},
                           "target": {"type": "string"}},
        },
        "features": {"type": ["array", "null"], "items": {"type": "string"}},
        "trials": {"type": ["integer", "null"], "minimum": 1},
        "trials_artifact": {"type": ["string", "null"]},
        "var_sr": {"type": ["number", "null"], "minimum": 0},
        "frictions": {
            "type": ["object", "null"], "additionalProperties": False,
            "properties": {
                "fee_bps": {"type": "number", "minimum": 0},
                "slippage_bps": {"type": "number", "minimum": 0},
                "borrow_bps": {"type": "number", "minimum": 0},
                "short_frac": {"type": "number", "minimum": 0},
                "adv": {"type": "number", "minimum": 0}, "size": {"type": "number", "minimum": 0},
                "participation": {"type": "number", "minimum": 0},
                "impact_coef": {"type": "number", "minimum": 0},
                "turnover": {"type": "number", "minimum": 0},
                "leverage": {"type": "number", "minimum": 0},
                "turnover_col": {"type": "string"}, "fill": {"type": "string"},
                "impact_model": {"type": "string"},
            },
        },
        "corpus": {
            "type": ["object", "null"], "additionalProperties": False, "required": ["manifest"],
            "properties": {"manifest": {"type": "string"}, "eval": {"type": "string"},
                           "eval_col": {"type": "string"}},
        },
    },
}
