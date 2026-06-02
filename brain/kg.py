"""Knowledge graph layer using NetworkX (pure Python, JSON-persisted).

Graph file: ~/.brain/kg/graph.json (node-link format, auto-saved on write).

Node types: Machine, Project, Tool, Document, Concept, Decision
Edge types: RUNS_ON, USES, DEPENDS_ON, BELONGS_TO, SUPERSEDES, RELATED_TO
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import networkx as nx

from .config import GLOBAL_KG, ensure_dirs

_GRAPH_FILE: pathlib.Path | None = None
_G: nx.DiGraph | None = None


def _graph_path() -> pathlib.Path:
    ensure_dirs()
    return GLOBAL_KG / "graph.json"


def _load() -> nx.DiGraph:
    global _G, _GRAPH_FILE
    path = _graph_path()
    _GRAPH_FILE = path
    if path.exists():
        try:
            data = json.loads(path.read_text())
            _G = nx.node_link_graph(data, directed=True, multigraph=False)
            return _G
        except Exception:
            pass
    _G = nx.DiGraph()
    return _G


def _save(g: nx.DiGraph) -> None:
    path = _graph_path()
    path.write_text(json.dumps(nx.node_link_data(g), indent=2))


def _g() -> nx.DiGraph:
    global _G
    if _G is None:
        _load()
    return _G


def init() -> None:
    _load()


def upsert_node(node_id: str, **attrs) -> None:
    g = _g()
    if g.has_node(node_id):
        g.nodes[node_id].update(attrs)
    else:
        g.add_node(node_id, **attrs)
    _save(g)


def upsert_edge(src: str, dst: str, rel: str, **attrs) -> None:
    g = _g()
    if not g.has_node(src):
        g.add_node(src)
    if not g.has_node(dst):
        g.add_node(dst)
    g.add_edge(src, dst, rel=rel, **attrs)
    _save(g)


def upsert_machine(name: str, tag: str, os_str: str, description: str, updated: str) -> None:
    upsert_node(f"machine:{name}", type="Machine", name=name, tag=tag,
                os=os_str, description=description, updated=updated)


def upsert_project(name: str, path: str, description: str, updated: str) -> None:
    upsert_node(f"project:{name}", type="Project", name=name, path=path,
                description=description, updated=updated)


def link_project_machine(project_name: str, machine_name: str) -> None:
    upsert_edge(f"project:{project_name}", f"machine:{machine_name}", "RUNS_ON")


def upsert_document(name: str, path: str, scope: str, chunks: int,
                    summary: str, updated: str) -> None:
    upsert_node(f"doc:{name}", type="Document", name=name, path=path,
                scope=scope, chunks=chunks, summary=summary, updated=updated)


def query(cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Simple pseudo-Cypher: 'MATCH (n:Type) RETURN n.field' style.

    Full Cypher is not supported — this is a best-effort subset for common patterns.
    For complex queries, call graph_neighbors() or graph_search() directly.
    """
    g = _g()
    results = []

    # Pattern: MATCH (n:Type {key: $param}) RETURN n.field
    import re
    m = re.search(r"MATCH\s+\((\w+):(\w+)(?:\s*\{([^}]+)\})?\)", cypher, re.IGNORECASE)
    ret = re.search(r"RETURN\s+(.+)", cypher, re.IGNORECASE)

    node_type = m.group(2) if m else None
    return_expr = ret.group(1).strip() if ret else None

    p = params or {}

    for node_id, attrs in g.nodes(data=True):
        if node_type and attrs.get("type", "").lower() != node_type.lower():
            continue
        if m and m.group(3):
            conditions = m.group(3)
            match = True
            for cond in conditions.split(","):
                cond = cond.strip()
                if ":" in cond:
                    k, v = cond.split(":", 1)
                    k = k.strip().lstrip("$")
                    v = v.strip().strip("\"'")
                    if v.startswith("$"):
                        v = str(p.get(v[1:], v))
                    if str(attrs.get(k, "")) != v:
                        match = False
                        break
            if not match:
                continue

        if return_expr:
            row = {}
            for expr in return_expr.split(","):
                expr = expr.strip()
                if "." in expr:
                    _, field = expr.rsplit(".", 1)
                    row[expr] = attrs.get(field)
                else:
                    row[expr] = attrs
            results.append(row)
        else:
            results.append(dict(attrs))

    return results


def graph_neighbors(node_id: str, rel: str | None = None) -> list[dict]:
    g = _g()
    if not g.has_node(node_id):
        return []
    results = []
    for src, dst, data in g.edges(node_id, data=True):
        if rel and data.get("rel") != rel:
            continue
        target = dst if dst != node_id else src
        results.append({"node": target, "rel": data.get("rel"), **g.nodes.get(target, {})})
    return results


def graph_search(query_str: str, node_type: str | None = None) -> list[dict]:
    g = _g()
    q = query_str.lower()
    results = []
    for node_id, attrs in g.nodes(data=True):
        if node_type and attrs.get("type", "").lower() != node_type.lower():
            continue
        searchable = " ".join(str(v) for v in attrs.values()).lower()
        if q in searchable:
            results.append({"node_id": node_id, **attrs})
    return results


def projects_on_machine(machine_tag: str) -> list[str]:
    g = _g()
    projects = []
    for node_id, attrs in g.nodes(data=True):
        if attrs.get("type") == "Machine" and attrs.get("tag") == machine_tag:
            for src, dst, data in g.in_edges(node_id, data=True):
                if data.get("rel") == "RUNS_ON":
                    src_attrs = g.nodes.get(src, {})
                    if src_attrs.get("type") == "Project":
                        projects.append(src_attrs.get("name", src))
    return projects


def documents_for_project(project_name: str) -> list[dict]:
    g = _g()
    docs = []
    proj_id = f"project:{project_name}"
    for src, dst, data in g.edges(data=True):
        if data.get("rel") == "BELONGS_TO" and dst == proj_id:
            doc_attrs = g.nodes.get(src, {})
            docs.append({"name": doc_attrs.get("name", src),
                         "summary": doc_attrs.get("summary", ""),
                         "scope": doc_attrs.get("scope", "")})
    return docs


def remove_document(name: str) -> None:
    g = _g()
    node_id = f"doc:{name}"
    if g.has_node(node_id):
        g.remove_node(node_id)
        _save(g)


def all_nodes(node_type: str | None = None) -> list[dict]:
    g = _g()
    results = []
    for node_id, attrs in g.nodes(data=True):
        if node_type and attrs.get("type", "").lower() != node_type.lower():
            continue
        results.append({"node_id": node_id, **attrs})
    return results
