"""Document ingestion pipeline.

Supports: .md, .txt, .py, .ts, .js, .pdf, and any plaintext file.
Chunks, embeds via RAG layer, extracts entities for KG.

Cross-repo: any path can be ingested, scoped to "global" or "repo".
"""

from __future__ import annotations

import datetime
import mimetypes
import pathlib
import re
from typing import Literal

Scope = Literal["global", "repo"]


def _read_text(path: pathlib.Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise RuntimeError("pypdf required for PDF ingestion: pip install pypdf")
    try:
        return path.read_text(errors="replace")
    except Exception as e:
        raise RuntimeError(f"Cannot read {path}: {e}") from e


def _extract_entities(text: str, doc_name: str) -> list[str]:
    """Heuristic entity extraction — finds capitalized phrases and code symbols."""
    entities = []
    # CamelCase symbols
    entities += re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text[:5000])
    # SCREAMING_SNAKE constants
    entities += re.findall(r"\b[A-Z_]{3,}\b", text[:3000])
    return list(dict.fromkeys(entities))[:30]


def ingest(
    path: str | pathlib.Path,
    scope: Scope = "repo",
    project: str | None = None,
    machine: str | None = None,
    ttl: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Ingest a file or directory into the brain.

    Returns summary dict: {doc_name, chunks, entities, scope, project}.
    """
    from . import kg, rag, mem as mem_mod
    from .config import GLOBAL_RAW, ensure_dirs, repo_brain

    path = pathlib.Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")

    if path.is_dir():
        results = []
        for child in sorted(path.rglob("*")):
            if child.is_file() and _is_ingestible(child):
                try:
                    results.append(ingest(child, scope=scope, project=project,
                                         machine=machine, ttl=ttl, cwd=cwd))
                except Exception:
                    pass
        return {"ingested_files": len(results), "files": [r["doc_name"] for r in results]}

    text = _read_text(path)
    if not text.strip():
        return {"doc_name": path.name, "chunks": 0, "skipped": "empty"}

    doc_name = path.stem
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

    chunks = rag.index_document(
        text=text,
        doc_name=doc_name,
        source_path=str(path),
        scope=scope,
        project=project,
        machine=machine,
    )

    entities = _extract_entities(text, doc_name)

    summary_text = text[:500].replace("\n", " ").strip()
    summary = f"{doc_name}: {summary_text}..."

    kg.upsert_document(
        name=doc_name,
        path=str(path),
        scope=scope,
        chunks=chunks,
        summary=summary[:300],
        updated=now,
    )
    if project:
        try:
            kg.link_project_machine(project, machine or "shared")
        except Exception:
            pass

    mem_mod.remember(
        content=f"doc:{doc_name} indexed — {summary[:200]}",
        agent_id=f"project:{project}" if project else "global",
        metadata={"doc_name": doc_name, "source_path": str(path), "scope": scope},
    )

    if scope == "global":
        ensure_dirs()
        _write_global_stub(doc_name, path, summary, now, ttl)
    elif cwd:
        _write_repo_stub(doc_name, path, summary, now, cwd)

    return {
        "doc_name": doc_name,
        "chunks": chunks,
        "entities": entities[:10],
        "scope": scope,
        "project": project,
    }


def _is_ingestible(path: pathlib.Path) -> bool:
    skip_dirs = {".git", ".brain", "node_modules", "__pycache__", ".venv", "venv"}
    for part in path.parts:
        if part in skip_dirs:
            return False
    suffix = path.suffix.lower()
    return suffix in {".md", ".txt", ".py", ".ts", ".js", ".tsx", ".jsx",
                      ".rs", ".go", ".c", ".cpp", ".h", ".pdf", ".yaml", ".yml", ".json"}


def _write_global_stub(doc_name: str, source: pathlib.Path, summary: str, now: str, ttl: str | None) -> None:
    from .config import GLOBAL_RAW
    import yaml
    stub_path = GLOBAL_RAW / f"doc_{doc_name}.md"
    meta = {
        "name": f"doc-{doc_name}",
        "description": summary[:120],
        "metadata": {
            "type": "reference",
            "machines": ["shared"],
            "updated": now,
            "ttl": ttl,
            "confidence": 1.0,
            "status": "active",
            "last_accessed": now,
            "access_count": 0,
            "source_path": str(source),
        },
    }
    content = "---\n" + yaml.dump(meta, default_flow_style=False) + "---\n\n"
    content += f"Indexed from: `{source}`\n\nSummary: {summary[:500]}\n"
    stub_path.write_text(content)


def _write_repo_stub(doc_name: str, source: pathlib.Path, summary: str, now: str, cwd: str) -> None:
    from .config import repo_brain
    docs_dir = repo_brain(cwd) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    stub = docs_dir / f"{doc_name}.md"
    stub.write_text(f"# {doc_name}\n\nSource: `{source}`\nIndexed: {now}\n\n{summary[:500]}\n")
