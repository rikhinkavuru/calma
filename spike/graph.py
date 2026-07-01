"""calma.spike.graph — inspect the verification knowledge graph.

The live graph of record is HelixDB when configured; this module gives the API and local UI a uniform view
of what Calma knows: curated formulas, lifted recipes, banked formulas, aliases, and recent job provenance.
"""
from __future__ import annotations

from core import catalog as C
from synth import store as S


def _node(nodes: dict, node_id: str, label: str, kind: str, **props):
    nodes[node_id] = {"id": node_id, "label": label, "kind": kind, **props}


def _edge(edges: list, src: str, dst: str, label: str, **props):
    edges.append({"source": src, "target": dst, "label": label, **props})


def _store_status(store):
    try:
        ok, detail = store.available()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)[:160]
    return {"name": getattr(store, "name", "unknown"), "available": ok, "detail": detail}


def build_graph(jobs=None, store=None) -> dict:
    """Return a portable graph representation for the local UI and API."""
    store = store or S.get_store()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    _node(nodes, "catalog:curated", "Curated catalog", "catalog")
    _node(nodes, "catalog:recipes", "Lifted recipe catalog", "catalog")
    _node(nodes, "store:%s" % getattr(store, "name", "unknown"), "%s formula store" % getattr(store, "name", "unknown"), "store")

    for metric in sorted(C.CATALOG):
        mid = "formula:catalog:%s" % metric
        _node(nodes, mid, metric, "formula", source="catalog")
        _edge(edges, "catalog:curated", mid, "contains")
    for alias, metric in sorted(C.ALIASES.items()):
        aid = "alias:%s" % alias
        _node(nodes, aid, alias, "alias")
        _edge(edges, aid, "formula:catalog:%s" % metric, "aliases")

    try:
        from recipes import adapter as RA

        reg = RA._recipes()
        recipe_ids = sorted(reg.list_ids() if hasattr(reg, "list_ids") else reg._REGISTRY)
    except Exception:  # noqa: BLE001
        recipe_ids = []
    for rid in recipe_ids:
        node_id = "formula:recipe:%s" % rid
        _node(nodes, node_id, rid, "formula", source="recipe")
        _edge(edges, "catalog:recipes", node_id, "contains")

    banked = []
    try:
        banked = store.all()
    except Exception:  # noqa: BLE001
        banked = []
    for rec in banked:
        node_id = "formula:banked:%s" % rec.metric
        _node(
            nodes,
            node_id,
            rec.metric,
            "formula",
            source=getattr(store, "name", "store"),
            aliases=rec.aliases,
            validation=rec.validation,
            definition=rec.definition,
        )
        _edge(edges, "store:%s" % getattr(store, "name", "unknown"), node_id, "stores")
        for alias in rec.aliases:
            aid = "alias:%s" % alias
            _node(nodes, aid, alias, "alias")
            _edge(edges, aid, node_id, "aliases")

    for job in jobs or []:
        jid = "job:%s" % job.get("id", "unknown")
        _node(nodes, jid, job.get("repo") or jid, "job", status=job.get("status"), counts=job.get("counts", {}))
        for claim in job.get("claims", []):
            cid = "claim:%s:%s" % (job.get("id", "unknown"), claim.get("id") or len(nodes))
            _node(
                nodes,
                cid,
                "%s %s" % (claim.get("metric"), claim.get("claimed")),
                "claim",
                verdict=claim.get("verdict"),
                reason=claim.get("reason"),
                provenance=claim.get("provenance"),
            )
            _edge(edges, jid, cid, "reported")
            metric = claim.get("metric")
            if metric:
                canonical = C.canonical(metric)
                target = "formula:catalog:%s" % canonical if canonical else None
                prov = claim.get("provenance") or ""
                formula = (claim.get("diff") or {}).get("formula")
                if prov.startswith("recipe"):
                    target = "formula:recipe:%s" % (formula or metric)
                elif "store" in prov or prov == "synth":
                    target = "formula:banked:%s" % (formula or metric)
                if target and target in nodes:
                    _edge(edges, cid, target, "recomputed_by")

    counts: dict = {}
    for n in nodes.values():
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return {"store": _store_status(store), "counts": counts, "nodes": list(nodes.values()), "edges": edges}


def html(graph: dict) -> str:
    """A small zero-build graph inspector."""
    rows = []
    for n in graph["nodes"]:
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _esc(n.get("kind")),
                _esc(n.get("label")),
                _esc(n.get("source") or n.get("status") or ""),
                _esc((n.get("validation") or {}).get("method") or n.get("verdict") or ""),
            )
        )
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>Calma Graph</title>
<style>body{font-family:system-ui;margin:32px;color:#191917;background:#fbfbfa}table{border-collapse:collapse;width:100%%}td,th{border-bottom:1px solid #e8e8e3;padding:8px;text-align:left}code{background:#f1f1ed;padding:2px 5px;border-radius:5px}.pill{display:inline-block;background:#191917;color:white;padding:3px 8px;border-radius:999px;margin-right:6px}</style>
</head><body><h1>Calma graph</h1>
<p>Store: <code>%s</code> · %s · <a href="/api/graph">raw JSON</a></p>
<p>%s</p>
<table><thead><tr><th>Kind</th><th>Node</th><th>Source / status</th><th>Validation / verdict</th></tr></thead><tbody>%s</tbody></table>
</body></html>""" % (
        _esc(graph["store"]["name"]),
        _esc(graph["store"]["detail"]),
        " ".join('<span class="pill">%s %s</span>' % (_esc(k), v) for k, v in sorted(graph["counts"].items())),
        "".join(rows),
    )


def _esc(value) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
