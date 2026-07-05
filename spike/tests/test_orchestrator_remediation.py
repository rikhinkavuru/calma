"""S1 — the fault taxonomy → HOW-only remediation registry. Fully hermetic: temp repos, no sandbox, no LLM.
Asserts the evidence collectors LICENSE only with sufficient in-repo evidence (constrained autonomy), that
propose() dispatches only WIRED + licensed remediations, and that the taxonomy stays firewall-clean."""
import os

from orchestrator import remediation as R


def _write(d, rel, body):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p) or d, exist_ok=True)
    with open(p, "w") as fh:
        fh.write(body)


# ── evidence: hardcoded data path ─────────────────────────────────────────────────────────────────────────────
def test_ev_committed_data_licenses_when_basename_committed(tmp_path):
    d = str(tmp_path)
    _write(d, "results/x.csv", "a,b\n1,2\n")                      # committed under results/
    ev = R._ev_committed_data(d, "FileNotFoundError: [Errno 2] No such file or directory: '/Users/me/dl/x.csv'")
    assert ev.licenses and not ev.facts["substitution"]
    assert ev.facts["committed_at"].replace("\\", "/") == "results/x.csv"


def test_ev_committed_data_licenses_sole_dataset_as_substitution(tmp_path):
    d = str(tmp_path)
    _write(d, "heart_cleveland.csv", "age,target\n60,1\n")        # the ONE committed dataset, different name
    ev = R._ev_committed_data(d, "No such file or directory: '/abs/heart.csv'")
    assert ev.licenses and ev.facts["substitution"] is True       # substitution → caller caps REPRODUCED-ONLY


def test_ev_committed_data_refuses_when_absent(tmp_path):
    d = str(tmp_path)
    _write(d, "a.csv", "x\n1\n")
    _write(d, "b.csv", "x\n1\n")                                   # two datasets → not a unique substitution
    assert not R._ev_committed_data(d, "No such file or directory: '/abs/absent.csv'").licenses
    assert not R._ev_committed_data(d, "some unrelated traceback").licenses   # no missing path named


# ── evidence: missing system binary (supply-chain rail) ───────────────────────────────────────────────────────
def test_ev_missing_binary_licenses_only_when_repo_declares_it(tmp_path):
    d = str(tmp_path)
    _write(d, "environment.yml", "name: e\ndependencies:\n  - python=3.11\n  - bedtools\n  - samtools=1.19\n")
    ev = R._ev_missing_binary(d, "bedtools: command not found")
    assert ev.licenses and ev.facts["binaries"] == ["bedtools"]   # allowlisted AND declared


def test_ev_missing_binary_refuses_when_not_declared(tmp_path):
    d = str(tmp_path)
    _write(d, "environment.yml", "dependencies:\n  - numpy\n")     # bedtools NOT declared
    assert not R._ev_missing_binary(d, "bedtools: command not found").licenses


def test_ev_missing_binary_refuses_non_allowlisted_name(tmp_path):
    d = str(tmp_path)
    _write(d, "README.md", "run `apt install totally-evil-tool`\n")
    # even declared, a non-allowlisted name is never parsed as a missing binary (supply-chain rail)
    assert not R._ev_missing_binary(d, "totally-evil-tool: command not found").licenses


# ── propose(): wired + licensed dispatch only ─────────────────────────────────────────────────────────────────
def test_propose_licenses_hardcoded_path(tmp_path):
    d = str(tmp_path)
    _write(d, "data/train.csv", "x\n1\n")
    plan = R.propose("missing-data", d, "No such file or directory: '/abs/train.csv'")
    assert plan and plan.action == "resolve_data_path" and "committed" in plan.detail


def test_propose_skips_unwired_missing_binary(tmp_path):
    d = str(tmp_path)
    _write(d, "environment.yml", "dependencies:\n  - bedtools\n")
    # evidence WOULD license it, but the main-path apply is not wired yet → propose returns None (honest).
    assert R._ev_missing_binary(d, "bedtools: command not found").licenses
    assert R.propose("missing-binary", d, "bedtools: command not found") is None


def test_propose_none_on_unknown_fault_or_no_repo(tmp_path):
    d = str(tmp_path)
    _write(d, "data/train.csv", "x\n1\n")
    assert R.propose("errored", d, "boom") is None
    assert R.propose("missing-data", None, "No such file or directory: '/abs/train.csv'") is None


# ── classify(): the structured taxonomy view ──────────────────────────────────────────────────────────────────
def test_classify_attaches_remediation_when_repo_given(tmp_path):
    d = str(tmp_path)
    _write(d, "x.csv", "a\n1\n")
    tax = R.classify("No such file or directory: '/abs/x.csv'", d)
    assert tax["kind"] == "missing-data" and tax["remediation"] == "resolve_data_path"
    assert tax["plan"] is not None and tax["evidence"]


def test_classify_plan_none_without_repo():
    tax = R.classify("No such file or directory: '/abs/x.csv'")
    assert tax["kind"] == "missing-data" and tax["plan"] is None and tax["remediation"] is None


def test_taxonomy_entries_are_wellformed():
    for kind, rems in R.REMEDIATIONS.items():
        for rem in rems:
            assert rem.fault == kind and rem.action and rem.summary and rem.validation
            assert callable(rem.evidence_fn)
