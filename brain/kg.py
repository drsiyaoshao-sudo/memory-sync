"""Knowledge graph layer using Kuzu embedded graph DB.

Schema:
  Node types: Machine, Project, Tool, Concept, Person, Decision, Document
  Edge types: RUNS_ON, USES, DEPENDS_ON, CREATED_BY, CONFLICTS_WITH, SUPERSEDES, BELONGS_TO, INDEXED_IN
"""

import pathlib
from typing import Any

import kuzu

from .config import GLOBAL_KG, ensure_dirs

_SCHEMA = """
CREATE NODE TABLE IF NOT EXISTS Machine(
    name STRING, tag STRING, os STRING, description STRING,
    updated STRING, PRIMARY KEY(name)
);
CREATE NODE TABLE IF NOT EXISTS Project(
    name STRING, path STRING, description STRING,
    updated STRING, PRIMARY KEY(name)
);
CREATE NODE TABLE IF NOT EXISTS Tool(
    name STRING, version STRING, machine STRING,
    PRIMARY KEY(name)
);
CREATE NODE TABLE IF NOT EXISTS Document(
    name STRING, path STRING, scope STRING, chunks INT,
    summary STRING, updated STRING, PRIMARY KEY(name)
);
CREATE NODE TABLE IF NOT EXISTS Concept(
    name STRING, description STRING, updated STRING,
    PRIMARY KEY(name)
);
CREATE NODE TABLE IF NOT EXISTS Decision(
    name STRING, summary STRING, scope STRING, updated STRING,
    PRIMARY KEY(name)
);
CREATE REL TABLE IF NOT EXISTS RUNS_ON(FROM Project TO Machine);
CREATE REL TABLE IF NOT EXISTS USES(FROM Project TO Tool);
CREATE REL TABLE IF NOT EXISTS DEPENDS_ON(FROM Project TO Project);
CREATE REL TABLE IF NOT EXISTS BELONGS_TO(FROM Document TO Project);
CREATE REL TABLE IF NOT EXISTS BELONGS_TO_MACHINE(FROM Document TO Machine);
CREATE REL TABLE IF NOT EXISTS SUPERSEDES(FROM Decision TO Decision);
CREATE REL TABLE IF NOT EXISTS RELATED_TO(FROM Concept TO Concept);
"""


def _db_path() -> pathlib.Path:
    ensure_dirs()
    return GLOBAL_KG


def _open() -> tuple[kuzu.Database, kuzu.Connection]:
    db = kuzu.Database(str(_db_path()))
    conn = kuzu.Connection(db)
    return db, conn


def init() -> None:
    db, conn = _open()
    for stmt in _SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt + ";")
            except Exception:
                pass  # table already exists
    db.close()


def upsert_machine(name: str, tag: str, os_str: str, description: str, updated: str) -> None:
    db, conn = _open()
    conn.execute(
        "MERGE (m:Machine {name: $name}) "
        "SET m.tag = $tag, m.os = $os, m.description = $desc, m.updated = $updated",
        {"name": name, "tag": tag, "os": os_str, "desc": description, "updated": updated},
    )
    db.close()


def upsert_project(name: str, path: str, description: str, updated: str) -> None:
    db, conn = _open()
    conn.execute(
        "MERGE (p:Project {name: $name}) "
        "SET p.path = $path, p.description = $desc, p.updated = $updated",
        {"name": name, "path": path, "desc": description, "updated": updated},
    )
    db.close()


def link_project_machine(project_name: str, machine_name: str) -> None:
    db, conn = _open()
    conn.execute(
        "MATCH (p:Project {name: $p}), (m:Machine {name: $m}) "
        "MERGE (p)-[:RUNS_ON]->(m)",
        {"p": project_name, "m": machine_name},
    )
    db.close()


def upsert_document(name: str, path: str, scope: str, chunks: int, summary: str, updated: str) -> None:
    db, conn = _open()
    conn.execute(
        "MERGE (d:Document {name: $name}) "
        "SET d.path = $path, d.scope = $scope, d.chunks = $chunks, "
        "d.summary = $summary, d.updated = $updated",
        {"name": name, "path": path, "scope": scope, "chunks": chunks,
         "summary": summary, "updated": updated},
    )
    db.close()


def query(cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
    db, conn = _open()
    result = conn.execute(cypher, params or {})
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    db.close()
    return rows


def projects_on_machine(machine_tag: str) -> list[str]:
    rows = query(
        "MATCH (p:Project)-[:RUNS_ON]->(m:Machine {tag: $tag}) RETURN p.name",
        {"tag": machine_tag},
    )
    return [r[0] for r in rows]


def documents_for_project(project_name: str) -> list[dict]:
    rows = query(
        "MATCH (d:Document)-[:BELONGS_TO]->(p:Project {name: $name}) "
        "RETURN d.name, d.summary, d.scope",
        {"name": project_name},
    )
    return [{"name": r[0], "summary": r[1], "scope": r[2]} for r in rows]


def remove_document(name: str) -> None:
    db, conn = _open()
    conn.execute("MATCH (d:Document {name: $name}) DETACH DELETE d", {"name": name})
    db.close()
