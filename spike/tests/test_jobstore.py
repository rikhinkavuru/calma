"""Durable job persistence — a finished run survives a 'redeploy' (a fresh JobStore over the same file)."""

from core import jobstore as JS


def _job(**kw):
    base = {"id": "abc123", "_tenant": "t1", "status": "done", "stage": "done", "progress": "",
            "created": 100.0, "updated": 200.0, "repo": "o/r", "logs": ["a", "b"],
            "counts": {"CONFIRMED": 2}, "n_claims": 2}
    base.update(kw)
    return base


def test_save_and_reload_terminal_job(tmp_path):
    path = str(tmp_path / "jobs.db")
    JS.JobStore(path).save(_job())
    reloaded = {j["id"]: j for j in JS.JobStore(path).load_all()}
    assert "abc123" in reloaded
    j = reloaded["abc123"]
    assert j["status"] == "done" and j["repo"] == "o/r"
    assert j["logs"] == ["a", "b"] and j["counts"] == {"CONFIRMED": 2}
    assert j["_tenant"] == "t1"                        # tenant preserved so the reload stays tenant-scoped


def test_running_job_reloads_as_interrupted(tmp_path):
    # A crash/redeploy while a job was mid-run must not resurrect it as a stuck 'running' — it is surfaced as
    # an honest error, and never holds a concurrency slot for a dead run.
    path = str(tmp_path / "jobs.db")
    JS.JobStore(path).save(_job(status="running", stage="running", _slot=True))
    j = JS.JobStore(path).load_all()[0]
    assert j["status"] == "error" and j["stage"] == "interrupted"
    assert "interrupted" in (j["error"] or "") and j["_slot"] is False


def test_upsert_overwrites(tmp_path):
    path = str(tmp_path / "jobs.db")
    s = JS.JobStore(path)
    s.save(_job(status="running"))
    s.save(_job(status="done", counts={"CONFIRMED": 5}))
    rows = s.load_all()
    assert len(rows) == 1 and rows[0]["status"] == "done" and rows[0]["counts"] == {"CONFIRMED": 5}


def test_load_all_newest_first_and_limit(tmp_path):
    path = str(tmp_path / "jobs.db")
    s = JS.JobStore(path)
    for i in range(5):
        s.save(_job(id="j%d" % i, created=float(i)))
    rows = s.load_all(limit=3)
    assert [r["id"] for r in rows] == ["j4", "j3", "j2"]


def test_missing_store_is_safe(tmp_path):
    # A broken/empty store must never raise into the engine.
    assert JS.JobStore(str(tmp_path / "sub" / "jobs.db")).load_all() == []
