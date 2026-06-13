"""WS3 intake: interpreter + dependency-source detection, dependency pinning selection, data-binding
by content hash, and the fail-soft restore contract. The actual pip/Rscript restore needs the network
and is exercised in the dress rehearsals; these checks are pure-stdlib and offline. Run: python3 test_intake.py
"""
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import intake as I  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _mk(base, files):
    for name, body in files.items():
        p = os.path.join(base, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(body)


# --- python repo with a loose requirements.txt + an input CSV ---
d = tempfile.mkdtemp()
_mk(d, {"main.py": "import pandas as pd\nprint('ok')\n",
        "requirements.txt": "pandas\nnumpy>=1.20\n# a comment\n",
        "data/prices.csv": "date,close\n1,100\n2,101\n"})
det = I.detect(d, {"run": {"entrypoint": "main.py"}})
truth(det["language"] == "python", "detect: python from a .py entrypoint")
kinds = {s["kind"] for s in det["dep_sources"]}
truth("requirements" in kinds, "detect: finds requirements.txt")
truth(any(b["path"] == "data/prices.csv" and b["sha256"] for b in I.data_bindings(d)),
      "data binding: input CSV is bound by content hash")
spec, method = I._pip_install_args(d, det["dep_sources"])
truth(spec == ["-r", os.path.join(d, "requirements.txt")], "pip spec: requirements.txt -> -r")

# --- pyproject (PEP 621) dependency extraction + precedence (requirements beats pyproject) ---
d2 = tempfile.mkdtemp()
_mk(d2, {"run.py": "print(1)\n",
         "pyproject.toml": "[project]\nname='x'\ndependencies = [\"vectorbt>=0.25\", \"numpy\"]\n",
         "requirements.txt": "pandas\n"})
det2 = I.detect(d2, {"run": {"entrypoint": "run.py"}})
truth({"requirements", "pyproject"} <= {s["kind"] for s in det2["dep_sources"]},
      "detect: both requirements and pyproject seen")
truth(I._parse_pyproject(os.path.join(d2, "pyproject.toml")) == ["vectorbt>=0.25", "numpy"],
      "pyproject: PEP 621 dependencies parsed")
spec2, _ = I._pip_install_args(d2, det2["dep_sources"])
truth(spec2 == ["-r", os.path.join(d2, "requirements.txt")], "precedence: requirements.txt wins over pyproject")

# pyproject-only repo -> pip install .
d2b = tempfile.mkdtemp()
_mk(d2b, {"run.py": "print(1)\n",
          "pyproject.toml": "[project]\nname='x'\ndependencies = [\"backtrader\"]\n"})
det2b = I.detect(d2b, {"run": {"entrypoint": "run.py"}})
spec2b, method2b = I._pip_install_args(d2b, det2b["dep_sources"])
truth(spec2b == ["."], "pyproject-only -> pip install .")

# --- R repo detection ---
d3 = tempfile.mkdtemp()
_mk(d3, {"analyze.R": "x <- 1\n", "renv.lock": "{}\n"})
det3 = I.detect(d3, {"run": {"entrypoint": "analyze.R"}})
truth(det3["language"] == "r", "detect: R from a .R entrypoint")
truth(any(s["kind"] == "renv.lock" for s in det3["r_sources"]), "detect: R renv.lock seen")

# --- intake() report shape (no restore: read-only, no network) ---
rep = I.intake(d, {"run": {"entrypoint": "main.py"}}, do_restore=False)
truth(rep["schema"] == "calma/intake@1", "intake report schema")
truth(rep["restored"] is False and rep["restore"] is None, "no-restore: nothing installed")
truth(rep["interpreter"]["version"].count(".") == 2, "intake captures the interpreter version")
truth(rep["data_bindings"], "intake captures data bindings")

# --- restore is FAIL-SOFT: a stdlib-only repo restores to a clean no-op (ok, no venv needed) ---
d4 = tempfile.mkdtemp()
_mk(d4, {"main.py": "print('stdlib only')\n"})
rr = I.restore_python(d4, [], timeout=30)
truth(rr["ok"] is True and not os.path.exists(os.path.join(d4, ".calma_venv")),
      "restore: stdlib repo -> ok, no venv created")

# data-binding hash matches a manual sha256 (the bytes the recompute is pinned to)
manual = hashlib.sha256(open(os.path.join(d, "data/prices.csv"), "rb").read()).hexdigest()
got = next(b["sha256"] for b in I.data_bindings(d) if b["path"] == "data/prices.csv")
truth(manual == got, "data-binding sha256 matches the file bytes exactly")

print("intake: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
