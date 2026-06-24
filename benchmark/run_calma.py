"""Run Calma over the benchmark corpus and score it against ground truth.

For each case: `calma verify <dir> "<claim>" --metric <id> --json --force`, map the verdict to a
prediction (REFUTED/MIXED/INVALIDATED -> flawed; CONFIRMED/CAVEATS -> honest; INCONCLUSIVE -> abstain), and
compare to the label. Emits results/calma.json and prints a confusion summary + per-case latency.
Run: python3 benchmark/run_calma.py
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(HERE_FILE := __file__))
CALMA = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts", "calma.py")


def _predict(verdict):
    # INVALIDATED is a catch (the number reproduces but the result is invalid - leaked/overfit/
    # survivorship-biased/gross-sold-as-net) - a "flawed" prediction, like REFUTED/MIXED.
    # FLAG_FOR_DECLARATION is also a catch (undeclared structure that would invalidate the headline; it
    # blocks the gate / IC auto-approval) - a "flawed" prediction, even though it is resolvable.
    if verdict in ("REFUTED", "MIXED", "INVALIDATED", "FLAG_FOR_DECLARATION"):
        return "flawed"
    if verdict in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"):
        return "honest"
    return "abstain"


def _restore_deps(case_dir):
    """A real-world repo with a requirements.txt needs its deps in <dir>/.calma_venv (the verify
    runs the entrypoint under that venv). One-time per checkout; pure-stdlib cases skip this.
    NOTE: pinned wheels may require python3.13 (pandas 2.2.3 has no cp314 wheels) - run this
    harness with a matching interpreter (see benchmark/README.md)."""
    req = os.path.join(case_dir, "requirements.txt")
    venv = os.path.join(case_dir, ".calma_venv")
    if not os.path.exists(req) or os.path.exists(venv):
        return
    print("  restoring deps for %s (one-time)..." % os.path.basename(case_dir))
    subprocess.run([sys.executable, "-m", "venv", venv], check=True, capture_output=True)
    subprocess.run([os.path.join(venv, "bin", "pip"), "install", "-q", "--only-binary=:all:",
                    "-r", req], check=True, capture_output=True, timeout=600)


def run():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    out = []
    for m in manifest:
        _restore_deps(m["dir"])
        t0 = time.time()
        # claim_text carries any convention the claim needs (e.g. "recall@5 0.62" -> k=5)
        p = subprocess.run([sys.executable, CALMA, "verify", m["dir"],
                            m.get("claim_text") or str(m["claim"]),
                            "--metric", m["metric"], "--json", "--force"],
                           capture_output=True, text=True)
        ms = int((time.time() - t0) * 1000)
        verdict, recomputed = "ERROR", None
        try:
            d = json.loads(p.stdout)
            verdict = d.get("verdict", "ERROR")
            recomputed = d.get("recomputed")
        except ValueError:
            pass
        pred = _predict(verdict)
        out.append({**{k: m[k] for k in ("id", "metric", "n_rows", "true_value", "claim", "label")},
                    "verdict": verdict, "recomputed": recomputed, "prediction": pred,
                    "correct": pred == m["label"], "ms": ms})
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "results", "calma.json"), "w"), indent=2)
    _summary("CALMA", out)
    return out


def _summary(name, rows):
    flawed = [r for r in rows if r["label"] == "flawed"]
    honest = [r for r in rows if r["label"] == "honest"]
    caught = sum(1 for r in flawed if r["prediction"] == "flawed")
    missed = sum(1 for r in flawed if r["prediction"] == "honest")      # FALSE CONFIRM (dangerous)
    abst_f = sum(1 for r in flawed if r["prediction"] == "abstain")
    false_alarm = sum(1 for r in honest if r["prediction"] == "flawed")  # FALSE REFUTE (dangerous)
    passed = sum(1 for r in honest if r["prediction"] == "honest")
    abst_h = sum(1 for r in honest if r["prediction"] == "abstain")
    lat = sorted(r["ms"] for r in rows)
    p50 = lat[len(lat) // 2] if lat else 0
    print("\n=== %s ===" % name)
    print("  flawed (%d): caught %d | MISSED/false-confirm %d | abstained %d"
          % (len(flawed), caught, missed, abst_f))
    print("  honest (%d): passed %d | FALSE-ALARM/false-refute %d | abstained %d"
          % (len(honest), passed, false_alarm, abst_h))
    catch_rate = caught / len(flawed) if flawed else 0.0
    print("  catch-rate (recall on flawed): %.0f%%   false-confirms: %d   false-alarms: %d   p50 latency: %dms"
          % (catch_rate * 100, missed, false_alarm, p50))
    return {"name": name, "flawed": len(flawed), "honest": len(honest), "caught": caught,
            "missed_false_confirm": missed, "abstain_flawed": abst_f, "passed": passed,
            "false_alarm_false_refute": false_alarm, "abstain_honest": abst_h,
            "catch_rate": catch_rate, "p50_ms": p50}


if __name__ == "__main__":
    run()
