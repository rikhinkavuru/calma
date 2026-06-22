# calma validity catalog -- the hardened validity cut

Every case below reproduces its headline number (a recompute / an LLM judge calls it honest) yet calma **INVALIDATES** it via the validity layer. Each is verified against the live engine, offline. This catalog is standalone -- it strengthens the validity-cut evidence (statistical N + citable provenance) without destabilizing the committed agent-arm benchmark.

**calma INVALIDATES 64 / 64** designed-to-catch cases across 8 families (>=8 per family).

| validity family | cases | calma INVALIDATES | citable provenance |
|---|---|---|---|
| omitted-costs | 8 | **8/8** | Novy-Marx & Velikov (2016), 'A Taxonomy of Anomalies and Their Trading Costs,' Review of Financial Studies 29(1):104-147. |
| survivorship | 8 | **8/8** | Brown, Goetzmann, Ibbotson & Ross (1992), 'Survivorship Bias in Performance Studies,' Review of Financial Studies 5(4):553-580. |
| window | 8 | **8/8** | Bailey, Borwein, Lopez de Prado & Zhu (2014), 'Pseudo-Mathematics and Financial Charlatanism,' Notices of the AMS 61(5):458-471. |
| data-snooping | 8 | **8/8** | Harvey & Liu (2014), 'Backtesting' (SSRN 2345489); Bailey & Lopez de Prado (2014), 'The Deflated Sharpe Ratio,' Journal of Portfolio Management 40(5):94-107. |
| model-leakage | 8 | **8/8** | Kaufman, Rosset, Perlich & Stitelman (2012), 'Leakage in Data Mining: Formulation, Detection, and Avoidance,' ACM TKDD 6(4), Article 15. |
| regime | 8 | **8/8** | McLean & Pontiff (2016), 'Does Academic Research Destroy Stock Return Predictability?,' Journal of Finance 71(1):5-32. |
| distribution-shift | 8 | **8/8** | Quinonero-Candela, Sugiyama, Schwaighofer & Lawrence, eds. (2009), 'Dataset Shift in Machine Learning,' MIT Press. |
| look-ahead | 8 | **8/8** | Luo, Alvarez, Wang, Jussa, Wang & Rohal (2014), 'Seven Sins of Quantitative Investing,' Deutsche Bank Markets Research. |

## calma's own misses (the honest ceiling)

Verification is not omniscience. These results are substantively flawed, yet calma CONFIRMS them -- disclosed so the boundary is explicit, not hidden.

| case | calma verdict | why calma misses it |
|---|---|---|
| miss_undeclared-haircut | CONFIRMED | The multiple-testing haircut only runs when a `study` block is declared. A producer who omits it -- or never knew to -- escapes the check. calma verifies what the contract declares; it does not infer an undeclared flaw. (Mitigation: calma draft/onboard proposes the blocks; the producer must adopt them.) |
| miss_corrupted-labels | CONFIRMED | calma recomputes the metric from the produced outputs; it cannot know the ground-truth labels are themselves wrong. Verifying that a number is correctly computed is not validating the truth of its inputs -- a different problem (data provenance), out of scope by design. |

_Regenerate / re-verify: `python3 benchmark/validity_catalog.py` (`--check` asserts the invariant as a regression gate)._
