"""Knowledge graph export tests."""
from graph import build_graph, html
from synth.store import LocalStore


def test_graph_includes_catalog_and_job_provenance(tmp_path):
    store = LocalStore(path=str(tmp_path / "formula_store.json"))
    job = {
        "id": "j1",
        "repo": "owner/repo",
        "status": "done",
        "counts": {"CONFIRMED": 1},
        "claims": [
            {
                "id": "c1",
                "metric": "accuracy",
                "claimed": "0.9",
                "verdict": "CONFIRMED",
                "provenance": "catalog",
                "diff": {"recomputed": 0.9},
            }
        ],
    }
    graph = build_graph([job], store=store)
    node_ids = {n["id"] for n in graph["nodes"]}
    edge_labels = {e["label"] for e in graph["edges"]}
    assert "formula:catalog:accuracy" in node_ids
    assert "job:j1" in node_ids
    assert "recomputed_by" in edge_labels
    assert graph["store"]["name"] == "local"
    assert "Calma graph" in html(graph)
