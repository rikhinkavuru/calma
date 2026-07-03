"""The four-unlocks capabilities (docs/FOUR-UNLOCKS-BUILD-PLAN.md): notebooks + conda + non-Python routing, the
Modal GPU backend, and the data-acquisition secret/egress hardening. Each new surface gets a CONFIRMED-shape
test and an honest-boundary test; the FCR invariant (no verdict in the transport) is re-checked structurally."""
import sys
import types

from runner import effector, egress, gpu
from runner import secrets as SEC


# ── runner.effector — the backend-agnostic contract ───────────────────────────────────────────────────────────
def test_capture_run_env_arms_the_shim():
    env = effector.capture_run_env(2, "/capture/calls_2.jsonl", hooks="sklearn",
                                   targets=[{"target": "m.f"}], fuzz=True)
    assert env["PYTHONPATH"] == effector.CAPTURE_MOUNT
    assert env["CALMA_CAPTURE_OUT"] == "/capture/calls_2.jsonl"
    assert env["CALMA_RUN_INDEX"] == "2"
    assert env["PYTHONHASHSEED"] == "0" and env["TZ"] == "UTC"
    assert env["CALMA_FUZZ"] == "1"
    assert '"m.f"' in env["CALMA_CAPTURE_TARGETS"]


def test_capture_run_env_extra_merges_last():
    env = effector.capture_run_env(0, "/o", extra={"HF_TOKEN": "x"})
    assert env["HF_TOKEN"] == "x"


def test_size_sandbox_life_covers_build_plus_k_runs_and_caps():
    assert effector.size_sandbox_life(600, 3, 600) == 600 + 3 * 600 + 120   # below the cap → exact
    assert effector.size_sandbox_life(10_000, 50, 3600, cap=3600) == 3600   # above the cap → clamped


def test_shape_result_ran_ok_and_cost():
    r = effector.shape_result([[{"a": 1}], []], [{"returncode": 0}, {"returncode": 0}],
                              build_seconds=5.0, run_seconds=3.0, extra_cost={"gpu_seconds": 8.0})
    assert r["ran_ok"] is True and r["n_calls"] == [1, 0]
    assert r["cost"]["sandbox_seconds"] == 8.0 and r["cost"]["gpu_seconds"] == 8.0


def test_shape_setup_error_is_honest_empty_not_a_verdict():
    r = effector.shape_setup_error("boom timeout", 2, 4.0)
    assert r["ran_ok"] is False and r["runs"] == [[], []]      # empty runs → downstream DISCOVERED, never CONFIRM
    assert r["meta"][0]["killed"] is True


# ── runner.gpu — GPU need detection ───────────────────────────────────────────────────────────────────────────
def test_gpu_scan_detects_cuda(tmp_path):
    (tmp_path / "train.py").write_text("import torch\nm = model.to('cuda')\n")
    res = gpu.scan_repo_for_gpu(str(tmp_path))
    assert res["needs_gpu"] is True and res["signals"]


def test_gpu_scan_requirements_token(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\ncupy-cuda12x\n")
    assert gpu.scan_repo_for_gpu(str(tmp_path))["needs_gpu"] is True


def test_gpu_scan_clean_repo_is_negative(tmp_path):
    (tmp_path / "eval.py").write_text("import numpy as np\nprint(np.mean([1,2,3]))\n")
    assert gpu.scan_repo_for_gpu(str(tmp_path))["needs_gpu"] is False


def test_needs_gpu_from_failure_uses_the_single_taxonomy():
    assert gpu.needs_gpu_from_failure("RuntimeError: No CUDA GPUs are available") is True
    assert gpu.needs_gpu_from_failure("ModuleNotFoundError: no module named x") is False


# ── runner.secrets — per-tenant store ─────────────────────────────────────────────────────────────────────────
def test_secret_store_set_list_redact():
    s = SEC.SecretStore()
    assert s.set_secret("t1", "HF_TOKEN", "hf_secretvalue") is True
    assert s.names("t1") == ["HF_TOKEN"]
    assert s.env_for("t1") == {"HF_TOKEN": "hf_secretvalue"}
    assert "hf_secretvalue" not in s.redact("token=hf_secretvalue done", "t1")


def test_secret_store_rejects_bad_names():
    s = SEC.SecretStore()
    assert s.set_secret("t1", "bad name", "v") is False
    assert s.set_secret("t1", "HF_TOKEN", "") is False
    assert s.names("t1") == []


def test_secret_store_tenant_isolation():
    s = SEC.SecretStore()
    s.set_secret("a", "HF_TOKEN", "aval")
    assert s.env_for("b") == {}                                # no cross-tenant read


# ── runner.egress — the acquire allowlist ─────────────────────────────────────────────────────────────────────
def test_egress_widens_per_credential():
    base = egress.allowlist_for([])
    with_hf = egress.allowlist_for(["HF_TOKEN"])
    assert "huggingface.co" in base                            # public data host always present
    assert any("hf.co" in h for h in with_hf)


def test_acquire_network_is_default_deny():
    net = egress.acquire_network(["HF_TOKEN"])
    assert net["deny_out"] == ["0.0.0.0/0"]                    # default-deny everything…
    assert "huggingface.co" in net["allow_out"]                # …then re-open exactly the data hosts


# ── core.limits — the GPU gate + meter ────────────────────────────────────────────────────────────────────────
def test_gpu_gate_enterprise_only():
    from core import limits as LIM
    lim = LIM.Limiter()
    ent, free = LIM.resolve_tier("enterprise"), LIM.resolve_tier("free")
    assert lim.admit_gpu("t", ent).ok is True
    d = lim.admit_gpu("t", free)
    assert d.ok is False and d.status == 402                   # free → hard gate, not a silent CPU downgrade


def test_paid_tiers_have_the_no_build_capabilities():
    """P6 (verify, no build): the custom-metric name-bind lifts to CONFIRMED via the AI plan, and entrypoint
    ambiguity is resolved by the orchestrator — both are on for paid, off for free by design."""
    from core import limits as LIM
    ent = LIM.resolve_tier("enterprise")
    assert ent.allow_ai_plan and ent.allow_orchestrator and ent.allow_gpu
    free = LIM.resolve_tier("free")
    assert not free.allow_ai_plan and not free.allow_orchestrator and not free.allow_gpu


def test_gpu_meter_exhaustion():
    from core import limits as LIM
    lim = LIM.Limiter()
    ent = LIM.resolve_tier("enterprise")
    lim.record_gpu_seconds("t", ent.gpu_minutes_per_month * 60 + 1)
    assert lim.admit_gpu("t", ent).ok is False                 # budget spent → declined (CPU verdict still stands)


def test_clamp_request_gates_explicit_gpu_on_free():
    from core import limits as LIM
    _out, d = LIM.clamp_request(LIM.resolve_tier("free"), {"gpu": True})
    assert d.ok is False and d.status == 402               # free → hard 402 regardless of flag


def test_gpu_passthrough_respects_fleet_flag(monkeypatch):
    from core import limits as LIM
    monkeypatch.setenv("CALMA_ENABLE_GPU", "on")
    out, d = LIM.clamp_request(LIM.resolve_tier("enterprise"), {"gpu": True})
    assert d.ok is True and out["allow_gpu"] is True       # enterprise + flag on → armed
    monkeypatch.setenv("CALMA_ENABLE_GPU", "off")
    out2, _ = LIM.clamp_request(LIM.resolve_tier("enterprise"), {"gpu": True})
    assert out2["allow_gpu"] is False                      # flag off → GPU-dark (inert by default)


# ── E2B command routing (four-unlocks §1/§3) ──────────────────────────────────────────────────────────────────
def test_command_for_routes_by_entry_kind():
    from runner.e2b_runner import _command_for
    assert _command_for("python", ["eval.py"]) == "python eval.py"                       # unchanged plain path
    assert "run_notebook_e2b.py" in _command_for("python", ["nb:a.ipynb"])
    assert _command_for("python", ["r:analyze.R"]).startswith("Rscript ")
    assert _command_for("python", ["julia:m.jl"]).startswith("julia ")


def test_lang_entrypoint_discovery(tmp_path):
    from orchestrator.tools_static import find_lang_entrypoints
    (tmp_path / "main.R").write_text("print('hi')\n")
    (tmp_path / "helper.jl").write_text("println(1)\n")
    found = dict(find_lang_entrypoints(str(tmp_path)))
    assert found["r"] == "main.R" and found["julia"] == "helper.jl"


def test_entry_kind_tags_lang():
    from orchestrator.tools_static import _entry_kind
    assert _entry_kind(["r:x.R"]) == "lang"
    assert _entry_kind(["nb:x.ipynb"]) == "notebook"
    assert _entry_kind(["eval.py"]) == "script"


# ── Modal GPU runner (fake SDK, offline) ──────────────────────────────────────────────────────────────────────
class _Proc:
    def __init__(self, out="", err=""):
        self.stdout = types.SimpleNamespace(read=lambda: out)
        self.stderr = types.SimpleNamespace(read=lambda: err)

    def wait(self):
        return 0


class _FileCtx:
    def __init__(self, sink=None, data=b""):
        self._sink, self._data = sink, data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, b):
        if self._sink is not None:
            self._sink.append(b)

    def read(self):
        return self._data


class _Sbx:
    created = 0

    def __init__(self, log):
        self.log = log

    @classmethod
    def create(cls, **kw):
        cls.created += 1
        _MLOG["gpu"] = kw.get("gpu")
        _MLOG["timeout"] = kw.get("timeout")
        return cls(_MLOG)

    def exec(self, *args, **kw):
        self.log.setdefault("cmds", []).append(" ".join(args))
        return _Proc()

    def open(self, path, mode="rb"):
        if "r" in mode and path.endswith(".jsonl") and ".hooks" not in path and ".fuzz" not in path:
            return _FileCtx(data=b'{"metric":"accuracy","result":0.9,"inputs":{"y_true":[1,0],"y_pred":[1,0]},"seq":0}\n')
        if "r" in mode and path.endswith(".hooks"):
            return _FileCtx(data=b'{"sklearn": true}')
        if "r" in mode:
            raise FileNotFoundError(path)
        return _FileCtx(sink=self.log.setdefault("writes", []))

    def terminate(self):
        self.log["terminated"] = self.log.get("terminated", 0) + 1


class _Image:
    def __getattr__(self, _name):
        return lambda *a, **k: self


_MLOG = {}


def _install_fake_modal(monkeypatch):
    global _MLOG
    _MLOG = {}
    _Sbx.created = 0
    fake = types.ModuleType("modal")
    fake.Sandbox = _Sbx
    fake.App = types.SimpleNamespace(lookup=lambda *a, **k: object())
    fake.Image = types.SimpleNamespace(debian_slim=lambda *a, **k: _Image())
    fake.Secret = types.SimpleNamespace(from_dict=lambda d: d)
    monkeypatch.setitem(sys.modules, "modal", fake)
    monkeypatch.setenv("MODAL_TOKEN_ID", "x")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "y")


def test_run_modal_creates_gpu_sandbox_and_meters(tmp_path, monkeypatch):
    _install_fake_modal(monkeypatch)
    (tmp_path / "eval.py").write_text("print('hi')\n")
    from runner.modal_runner import run_modal
    res = run_modal(str(tmp_path), ["eval.py"], k=2, gpu="A100", pip_install=None)
    assert _Sbx.created == 1 and _MLOG["gpu"] == "A100"
    assert len(res["runs"]) == 2 and res["ran_ok"]
    assert res["cost"]["gpu_seconds"] >= 0 and res["cost"]["gpu"] == "A100"
    assert _MLOG.get("terminated", 0) == 1                     # sandbox torn down
    assert sum(1 for c in _MLOG.get("cmds", []) if "python eval.py" in c) == 2   # ran k×


def test_run_modal_degrades_honestly_without_sdk(tmp_path, monkeypatch):
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.setitem(sys.modules, "modal", None)           # force import failure path
    from runner.modal_runner import run_modal
    res = run_modal(str(tmp_path), ["eval.py"], k=1)
    assert res["ran_ok"] is False and res["runs"] == [[]]      # honest empty — CPU verdict stands, no crash


def test_modal_runner_has_no_verdict_surface():
    """FCR: the GPU transport must not import or reach the verdict core — it only returns the repo's OWN
    captured computations (like every other runner). Structural check mirroring the orchestrator firewall."""
    import ast
    import inspect

    from runner import modal_runner
    tree = ast.parse(inspect.getsource(modal_runner))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any(m in imported for m in ("core.verdict", "core.diff")), imported


# ── reproduction fixes (composition-confound-vep post-mortem 2026-07-02) ───────────────────────────────────────
def test_sandbox_python_default():
    from runner import build
    assert build.sandbox_python()                              # never empty; drives the era-pin relax floor


def test_era_pin_relaxes_incompatible_pin_without_declared_python(tmp_path, monkeypatch):
    """A repo that declares NO Python still gets its era-pins relaxed against the sandbox interpreter — the
    numpy==2.5.0-needs-3.12-on-a-3.11-image bug. Without this the pin installs blind and the whole run fails."""
    from orchestrator.tools_exec import era_pin_compat
    monkeypatch.setenv("CALMA_SANDBOX_PY", "3.11")            # image ships 3.11
    out, _era, notes = era_pin_compat(["numpy==2.5.0"], str(tmp_path), None,
                                      requires_python_fn=lambda n, v: ">=3.12")
    assert "numpy" in out and "numpy==2.5.0" not in out        # relaxed to bare name
    assert any("relaxed numpy" in n for n in notes)


def test_pyarrow_parquet_engine_error_heals(tmp_path):
    import pipeline as P
    rr = {"meta": [{"stderr_tail": "ImportError: Unable to find a usable engine; tried using: 'pyarrow', "
                                   "'fastparquet'. A suitable version of pyarrow or fastparquet is required"}]}
    assert P._missing_module_from(rr) == "pyarrow"            # → the heal installs pyarrow + retries


def test_parquet_engine_classified_missing_dep():
    from runner import build
    assert build.classify_failure("Unable to find a usable engine").get("kind") == "missing-dep"


def test_orchestrator_missing_module_detects_pyarrow():
    from orchestrator.orchestrate import _missing_module
    from orchestrator.types import RunResult
    rr = RunResult(ran_ok=False, meta=[{"stderr_tail": "Unable to find a usable engine; tried using: 'pyarrow'"}])
    assert _missing_module(rr) == "pyarrow"


def test_execute_stops_on_missing_data_instead_of_grinding_the_ladder():
    """Repetition fix: a missing-data failure on the top entrypoint must STOP the loop (a different entrypoint
    can't conjure the file) — not grind every fallback (figures/notebook) in its own microVM, twice."""
    from orchestrator.orchestrate import Budget, execute
    from orchestrator.types import RunApproach, RunResult
    tried = []

    def run_approach(a):
        tried.append(a.entry[0])
        if a.entry[0] == "compute.py":
            return RunResult(ran_ok=False, runs=[],
                             meta=[{"stderr_tail": "FileNotFoundError: data/clinvar.parquet", "returncode": -9}])
        return RunResult(ran_ok=True, runs=[[{"metric": "acc"}]], meta=[{"returncode": 0}])

    approaches = [RunApproach(entry=["compute.py"]), RunApproach(entry=["figures.py"])]
    res = execute(approaches, run_approach, budget=Budget(step_cap=6, max_approaches=4))
    assert tried == ["compute.py"]                            # stopped — never burned a sandbox on figures.py
    assert not res.ran_ok


def test_acquire_installs_download_script_deps(tmp_path):
    """The download scripts need their OWN deps (datasets/huggingface_hub) — without them the first acquire step
    ImportErrors before a byte downloads (composition-confound-vep: '01_get_traitgym.py: from datasets import')."""
    from runner.e2b_runner import _acquire_deps
    (tmp_path / "01_get.py").write_text("from datasets import load_dataset\nimport requests\n")
    deps = _acquire_deps(str(tmp_path), [["01_get.py"]])
    assert "datasets" in deps and "huggingface_hub" in deps and "requests" in deps


# ── data-source bypass (fetch canonical data directly when the repo's scripts fail) ────────────────────────────
def test_planner_data_sources_validation():
    from planner import _valid_data_sources
    ok = _valid_data_sources([
        {"path": "data/clinvar/clinvar.vcf.gz", "url": "https://ftp.ncbi.nlm.nih.gov/x/clinvar.vcf.gz"},
        {"path": "../etc/passwd", "url": "https://evil/x"},          # traversal → dropped
        {"path": "/abs", "url": "https://evil/x"},                   # absolute → dropped
        {"path": "data/x", "url": "http://insecure/x"},             # non-https → dropped
        {"path": "data/y", "url": "file:///etc/shadow"},            # non-https → dropped
    ])
    assert ok == [{"path": "data/clinvar/clinvar.vcf.gz", "url": "https://ftp.ncbi.nlm.nih.gov/x/clinvar.vcf.gz"}]


def test_auto_resolved_data_caps_refute_to_inconclusive():
    """A mismatch against AUTO-FETCHED data must not false-REFUTE (it may be a data-version diff). It caps to
    INCONCLUSIVE; a match would still CONFIRM. Verified via the _diff_claims cap directly."""
    import pipeline as P
    from core import verdict as VD

    class _FakeDiff:
        @staticmethod
        def diff_claim(claim, runs, **kw):
            return {"verdict": VD.REFUTED, "reason": "claimed 0.9 != produced 0.7", "diff": {}}

    orig = P.D
    P.D = _FakeDiff()
    try:
        claims = [{"id": "c1", "metric": "roc_auc", "value": "0.9"}]
        run = {"runs": [[{"metric": "roc_auc", "result": 0.7}]], "data_auto_resolved": True}
        recs = P._diff_claims(claims, run, {"ran": True})
        assert recs[0]["verdict"] == VD.INCONCLUSIVE            # capped, not REFUTED
        run2 = {"runs": [[{"metric": "roc_auc", "result": 0.7}]]}   # no auto-resolve → REFUTED stands
        assert P._diff_claims(claims, run2, {"ran": True})[0]["verdict"] == VD.REFUTED
    finally:
        P.D = orig


def test_data_catalog_augments_and_dedupes():
    from runner import data_catalog as CAT
    # data_needed mentions clinvar + GRCh38 → both canonical URLs added
    out = CAT.augment_sources([], "Needs ClinVar VCF and the GRCh38 reference genome")
    urls = {s["url"] for s in out}
    assert any("clinvar.vcf.gz" in u for u in urls)
    assert any("GRCh38" in u for u in urls)
    # a plan source already covering clinvar is not duplicated
    pre = [{"path": "d/clinvar.vcf.gz", "url": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz"}]
    out2 = CAT.augment_sources(pre, "clinvar")
    assert sum(1 for s in out2 if "clinvar.vcf.gz" in s["url"]) == 1     # deduped by URL


# ── reactive exact-path data resolution (the "imperfect repo" fallback) ────────────────────────────────────────
def test_missing_files_extracted_from_repo_errors():
    from runner.e2b_runner import _missing_files_from
    t = ("FileNotFoundError: [Errno 2] No such file or directory: '/work/data/clinvar/clinvar.vcf.gz'\n"
         "Reading VCF: /work/data/ref/GRCh38.fa Failed to open")
    assert _missing_files_from(t) == ["data/clinvar/clinvar.vcf.gz", "data/ref/GRCh38.fa"]


def test_reactive_acquire_resolves_missing_file_and_reruns():
    """The core imperfect-repo fallback: a step fails on a missing file → resolve its URL (catalog) → fetch to the
    EXACT path the repo reported → re-run the step → it succeeds. No path-guessing (the repo names the path)."""
    import types

    from runner import e2b_runner as E
    st = {"clinvar": False}

    class _Cmd:
        def run(self, cmd, **kw):
            if "curl" in cmd and "clinvar" in cmd:                 # a fetch of clinvar lands the file
                st["clinvar"] = True
                return types.SimpleNamespace(exit_code=0, stdout="", stderr="")
            if "03_get_clinvar" in cmd:                            # step 03 fails until clinvar is present
                if st["clinvar"]:
                    return types.SimpleNamespace(exit_code=0, stdout="", stderr="")
                return types.SimpleNamespace(exit_code=1, stdout="",
                                             stderr="FileNotFoundError: '/work/data/clinvar/clinvar.vcf.gz'")
            return types.SimpleNamespace(exit_code=0, stdout="", stderr="")

    class _Sbx:
        commands = _Cmd()

    n_ok, n_res = E._run_acquire(_Sbx(), [["03_get_clinvar.py"]], "python", 60, None)
    assert n_res >= 1 and n_ok == 1                                # resolved via catalog, step then succeeded


def test_missing_binary_detection_is_allowlisted():
    from runner.e2b_runner import _missing_binaries_from
    assert _missing_binaries_from("FileNotFoundError: [Errno 2] No such file or directory: 'bedtools'") == ["bedtools"]
    assert _missing_binaries_from("samtools: command not found") == ["samtools"]
    assert _missing_binaries_from("No such file or directory: 'rm_rf_evil'") == []   # not allowlisted → refused
    assert _missing_binaries_from("No such file or directory: 'data/x.vcf.gz'") == [] # a path, not a bare tool


# ── multi-script pipeline entrypoint ranking (metric is in a LATE script, not the obvious one) ─────────────────
def test_pipeline_ranking_prefers_metric_script(tmp_path):
    from orchestrator.tools_static import find_entrypoints, find_pipeline_entrypoints
    code = tmp_path / "code"
    code.mkdir()
    (code / "01_download.py").write_text("from datasets import load_dataset\nload_dataset('x')\n")
    (code / "05_compute_features.py").write_text("import pandas as pd\ndf.to_parquet('feat.parquet')\n")
    (code / "12_e5_e6.py").write_text("from sklearn.metrics import roc_auc_score\n"
                                      "a = roc_auc_score(y, p)\nout.to_csv('e5_calibration.csv')\n")
    (code / "13_figures.py").write_text("import matplotlib.pyplot as plt\nplt.plot(x)\n")
    ranked = find_pipeline_entrypoints(str(tmp_path))
    assert ranked and ranked[0][0] == ["code/12_e5_e6.py"]          # the metric computer ranks first
    # and it beats the data-prep script in the overall entrypoint ranking
    top = find_entrypoints(str(tmp_path))
    argvs = [c.argv for c in top]
    assert ["code/12_e5_e6.py"] in argvs
    i_metric = argvs.index(["code/12_e5_e6.py"])
    assert not any(a == ["code/05_compute_features.py"] and argvs.index(a) < i_metric for a in argvs)


def test_pipeline_ranking_empty_for_non_pipeline(tmp_path):
    from orchestrator.tools_static import find_pipeline_entrypoints
    (tmp_path / "eval.py").write_text("print(1)\n")
    assert find_pipeline_entrypoints(str(tmp_path)) == []           # not a numbered pipeline


# ── context-aware binding (confirm a whole benchmark table in one run, not number-by-number) ───────────────────
def test_capture_extracts_semantic_context():
    import calma_capture as CC
    ctx = CC._extract_context({"dataset": "human_nontata_promoters", "clf": "rf", "acc": 0.86,
                               "path": "/tmp/x", "long": "z" * 100})
    assert ctx == {"dataset": "human_nontata_promoters", "clf": "rf"}   # names/paths/values excluded


def test_context_binding_disambiguates_same_metric():
    """A benchmark computes accuracy for many model×dataset cells → same metric, many captures. The claim's row
    context binds it to the RIGHT capture (semantic, not value), so a leaderboard confirms in one pass."""
    from core.diff import _bound_call
    claim = {"metric": "accuracy", "value": 0.86, "context": "dataset=human_nontata_promoters model=RF"}
    calls = [
        {"metric": "accuracy", "result": 0.86, "user_site": True, "site": "a.py:5",
         "context": {"dataset": "human_nontata_promoters", "clf": "rf"}},
        {"metric": "accuracy", "result": 0.72, "user_site": True, "site": "a.py:9",
         "context": {"dataset": "human_enhancers", "clf": "cnn"}},
    ]
    call, status, reason = _bound_call(claim, calls)
    assert status == "bound" and call["result"] == 0.86 and "context match" in reason


def test_context_binding_is_not_value_binding():
    """Safety: context match is by dataset/model tokens, NEVER the value. Two captures with the SAME context but
    different values stay ambiguous (context can't disambiguate them) — recompute, not value, must decide."""
    from core.diff import _bound_call
    claim = {"metric": "accuracy", "value": 0.9, "context": "dataset=d1 model=m1"}
    calls = [
        {"metric": "accuracy", "result": 0.9, "user_site": True, "site": "a.py:5", "context": {"dataset": "d1"}},
        {"metric": "accuracy", "result": 0.4, "user_site": True, "site": "a.py:5", "context": {"dataset": "d1"}},
    ]
    _call, status, _reason = _bound_call(claim, calls)
    assert status != "bound"          # same context both → NOT uniquely bound by context (never picks by value)
