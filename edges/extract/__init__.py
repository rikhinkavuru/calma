"""edges.extract — A1 claim-graph extraction.

P1.1 (this module's `ingest`) turns any artifact (notebook / PDF / dataset) into a normalized
ArtifactBundle of provenance-tagged text spans + the raw data files Calma will recompute over.
Pure parsing: no model call, no network, no randomness, and no rewriting of a recompute-able file
(the engine must recompute over the author's exact bytes). Downstream prompts (P1.2 extractor,
P1.3 contract adapter) build on the bundle this module emits.
"""
