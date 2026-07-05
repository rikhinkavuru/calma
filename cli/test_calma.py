"""calma CLI — offline smoke tests (argument parsing + rendering + the verify poll loop, requests mocked)."""

import json

import calma


def test_parser_verify_defaults():
    args = calma.build_parser().parse_args(["verify", "owner/repo", "--deep"])
    assert args.repo == "owner/repo" and args.deep is True and args.cmd == "verify"


def test_fmt_counts_orders_actionable_first():
    out = calma._fmt_counts({"DISCOVERED": 3, "REFUTED": 1, "CONFIRMED": 2})
    assert out.index("refuted") < out.index("confirmed") < out.index("discovered")
    assert calma._fmt_counts({}) == "—"


def test_verify_polls_to_done(monkeypatch, capsys):
    calls = {"n": 0}

    def fake_request(method, path, body=None, want_text=False):
        if method == "POST":
            return {"id": "job1", "tier": "pro", "deep": True, "limit_notes": []}
        calls["n"] += 1
        if calls["n"] < 2:
            return {"status": "running", "progress": "run 1/2 · 3m elapsed"}
        return {"status": "done", "repo": "owner/repo", "counts": {"CONFIRMED": 2, "REFUTED": 1},
                "n_claims": 3, "run": {"entry": "run.py", "calls": 3}}

    monkeypatch.setattr(calma, "_request", fake_request)
    monkeypatch.setattr(calma.time, "sleep", lambda *_: None)
    rc = calma.main(["verify", "owner/repo", "--deep"])
    out = capsys.readouterr().out
    assert rc == 1                                  # a REFUTED present → non-zero exit (CI-friendly)
    assert "job1 submitted" in out and "run 1/2 · 3m elapsed" in out
    assert "confirmed:2" in out and "refuted:1" in out


def test_scans_json(monkeypatch, capsys):
    monkeypatch.setattr(calma, "_request", lambda *a, **k: [{"id": "j1", "repo": "o/r", "status": "done",
                                                             "counts": {"CONFIRMED": 1}}])
    rc = calma.main(["scans", "--json"])
    assert rc == 0 and json.loads(capsys.readouterr().out)[0]["id"] == "j1"
