.PHONY: install uninstall test test-all eval controls validity-catalog demo benchmark

SKILL := .claude/skills/calma

install:        ## put `calma` on your PATH (symlink; no deps)
	@./install.sh

uninstall:      ## remove the `calma` symlink from common bin dirs
	@for d in "$$HOME/.local/bin" /usr/local/bin; do \
	  if [ -L "$$d/calma" ]; then \
	    rm -f "$$d/calma" 2>/dev/null && echo "removed $$d/calma" || echo "could not remove $$d/calma (try sudo)"; \
	  fi; \
	done

test:           ## run the core suite (pure stdlib, no venv needed)
	@python3 $(SKILL)/scripts/tests/run_all.py

test-all:       ## run EVERY layer: core + mcp + pr (bootstraps ~/.calma venvs if missing)
	@bash scripts/test_all.sh

eval:           ## the standing eval net: core suite + framework golden vectors + recompute baseline + determinism
	@bash scripts/eval.sh

controls:       ## run the 4 SOC 2 controls (§1.2) -> a dated evidence pack (isolation/egress/no-raw/integrity)
	@python3 $(SKILL)/scripts/soc2_controls.py --out soc2-evidence.json && echo "  wrote soc2-evidence.json"

validity-catalog: ## regenerate + verify the hardened validity cut (>=8 INVALIDATED cases/family, live engine)
	@python3 benchmark/validity_catalog.py --check

demo:           ## watch a real inflated backtest get caught
	@python3 $(SKILL)/scripts/calma.py demo

benchmark:      ## synthetic-only quick track (NOT the published 117-case run; overwrites committed results)
	@echo "note: synthetic-only (84 cases) Calma-side track. This OVERWRITES the committed"
	@echo "      benchmark/results/{summary,site_data}.json with synthetic-only numbers and does NOT"
	@echo "      reproduce the published 117-case figures. See benchmark/README.md 'Reproduce' for the full run."
	@python3 benchmark/gen_corpus.py && python3 benchmark/run_calma.py && python3 benchmark/score.py
