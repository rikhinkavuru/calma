.PHONY: install uninstall test demo benchmark

SKILL := .claude/skills/calma

install:        ## put `calma` on your PATH (symlink; no deps)
	@./install.sh

uninstall:      ## remove the `calma` symlink from common bin dirs
	@for d in "$$HOME/.local/bin" /usr/local/bin; do \
	  if [ -L "$$d/calma" ]; then rm -f "$$d/calma" && echo "removed $$d/calma"; fi; \
	done

test:           ## run the full test suite (pure stdlib)
	@python3 $(SKILL)/scripts/tests/run_all.py

demo:           ## watch a real inflated backtest get caught
	@python3 $(SKILL)/scripts/calma.py demo

benchmark:      ## rebuild + score the catch-a-wrong-number benchmark (calma side)
	@python3 benchmark/gen_corpus.py && python3 benchmark/run_calma.py && python3 benchmark/score.py
