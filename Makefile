# Calma quality gate — the single command that runs the full production gate.
#
#   make gate      # run EVERYTHING (Python + FCR + web + secrets). The definition-of-done bar.
#   make py        # Python side only        make web      # web side only
#   make py-test   # fast test run (no coverage), for the inner dev loop
#
# Tooling location is configurable so the same targets work locally and in CI:
#   local (default) -> the proven spike venv at ~/.calma/spike-venv/bin/  (trailing slash required)
#   CI              -> `make gate V=`  uses PATH-installed tools (setup-python + pip install)
V ?= $(HOME)/.calma/spike-venv/bin/
COV_MIN ?= 73          # critical-surface floor (Phase 1 baseline = 73.4%); ratchet up as coverage grows.

.PHONY: gate py web py-test py-cov py-lint py-type py-dead fcr audit secrets \
        web-type web-lint web-build web-audit

# Full gate — every check the definition-of-done requires. Green here == shippable.
gate: py web secrets
	@echo "== GATE PASSED =="

# ---------------------------------------------------------------- Python (spike/)
# Python gate: lint -> types -> dead-code -> tests+coverage -> FCR franchise -> CVE audit
py: py-lint py-type py-dead py-cov fcr audit

# full suite, no coverage (fast inner loop)
py-test:
	cd spike && $(V)python -m pytest tests -q

# full suite + critical-surface coverage floor
py-cov:
	cd spike && $(V)python -m pytest tests -q \
	  --cov=core --cov=capture --cov=discovery --cov=runner --cov=synth --cov=server --cov=pipeline \
	  --cov-report=term-missing:skip-covered --cov-fail-under=$(COV_MIN)

# ruff (config: spike/ruff.toml)
py-lint:
	cd spike && $(V)ruff check .

# mypy — 0 errors across the source tree
py-type:
	cd spike && $(V)mypy core capture discovery synth runner optimize attest connect orchestrator hook *.py --ignore-missing-imports

# vulture — no dead code at confidence >= 80
py-dead:
	cd spike && $(V)vulture core capture discovery synth runner optimize attest connect orchestrator hook *.py --min-confidence 80

# the FCR franchise gates — false-confirm=0 invariant; each MUST exit 0
fcr:
	cd spike && for g in redteam formula_fuzz_eval metamorphic_eval fabrication repair stochastic anomaly_eval xcheck_eval interval_eval bounty convention_fuzz edgecases; do \
	  $(V)python optimize/$$g.py >/dev/null && echo "fcr:$$g OK" || { echo "fcr:$$g FAIL"; exit 1; }; \
	done

# pip-audit — 0 known high/critical CVEs in the shipped runtime deps
audit:
	cd spike && $(V)pip-audit -r requirements.txt

# ---------------------------------------------------------------- cross-cutting
# detect-secrets over all TRACKED files; fails only on a secret NOT in .secrets.baseline
secrets:
	git ls-files -z | xargs -0 $(V)detect-secrets-hook --baseline .secrets.baseline

# ---------------------------------------------------------------- Web (web/)
# Web gate: types -> lint(0 warnings) -> build -> dep audit
web: web-type web-lint web-build web-audit

# tsc --noEmit — 0 type errors
web-type:
	cd web && npx --no-install tsc --noEmit

# next lint — 0 warnings (stricter than `npm run lint`, which tolerates warnings)
web-lint:
	cd web && npx --no-install next lint --max-warnings=0

# production build must succeed
web-build:
	cd web && npm run build

# npm audit — 0 high/critical
web-audit:
	cd web && npm audit --omit=dev --audit-level=high
