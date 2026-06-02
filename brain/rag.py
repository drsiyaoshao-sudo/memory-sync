"""RAG layer: chunked document retrieval via Mem0's vector store.

Documents are chunked, embedded, and stored with metadata including:
  - scope: "global" | "repo" | "machine"
  - project: project name (optional)
  - machine: hostname tag (optional)
  - doc_name: logical document name for retrieval
  - source_path: original file path
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from .config import MEM0_CONFIG, ensure_dirs

_CHUNK_SIZE = 1000   # tokens approx (chars / 4)
_CHUNK_OVERLAP = 100

_client = None
_RAG_AGENT_ID = "rag_corpus"


def _get_client():
    global _client
    if _client is None:
        ensure_dirs()
        from mem0 import Memory
        _client = Memory.from_config(MEM0_CONFIG)
    return _client


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    chars_per_chunk = size * 4
    overlap_chars = overlap * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + chars_per_chunk
        chunks.append(text[start:end])
        start += chars_per_chunk - overlap_chars
    return [c.strip() for c in chunks if c.strip()]


def _doc_agent_id(scope: str, project: str | None, machine: str | None) -> str:
    parts = [f"rag:{scope}"]
    if project:
        parts.append(f"project:{project}")
    if machine:
        parts.append(f"machine:{machine}")
    return ":".join(parts)


def index_document(
    text: str,
    doc_name: str,
    source_path: str,
    scope: str = "global",
    project: str | None = None,
    machine: str | None = None,
) -> int:
    """Chunk and embed a document. Returns number of chunks stored."""
    m = _get_client()
    chunks = _chunk_text(text)
    agent_id = _doc_agent_id(scope, project, machine)

    for i, chunk in enumerate(chunks):
        meta = {
            "doc_name": doc_name,
            "source_path": source_path,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "scope": scope,
        }
        if project:
            meta["project"] = project
        if machine:
            meta["machine"] = machine
        m.add(chunk, agent_id=agent_id, metadata=meta)

    return len(chunks)


def query(
    q: str,
    scope: str | None = None,
    project: str | None = None,
    machine: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Semantic search over indexed document chunks.

    If scope/project/machine are given, searches the specific agent_id.
    Otherwise searches across all rag: namespaces and merges results.
    """
    m = _get_client()

    if scope:
        agent_id = _doc_agent_id(scope, project, machine)
        results = m.search(q, agent_id=agent_id, limit=limit)
        if isinstance(results, dict):
            results = results.get("results", [])
        return _format(results)

    all_results: list[dict] = []
    seen: set[str] = set()
    for agent_id in _known_rag_agent_ids():
        try:
            hits = m.search(q, agent_id=agent_id, limit=limit)
            if isinstance(hits, dict):
                hits = hits.get("results", [])
            for h in hits:
                key = h.get("id", h.get("memory", ""))
                if key not in seen:
                    seen.add(key)
                    h["_agent_id"] = agent_id
                    all_results.append(h)
        except Exception:
            pass

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return _format(all_results[:limit])


def _format(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        out.append({
            "text": r.get("memory", r.get("text", "")),
            "score": r.get("score", 0.0),
            "doc_name": r.get("metadata", {}).get("doc_name", "unknown"),
            "source_path": r.get("metadata", {}).get("source_path", ""),
            "chunk_index": r.get("metadata", {}).get("chunk_index", 0),
            "scope": r.get("metadata", {}).get("scope", ""),
            "project": r.get("metadata", {}).get("project", ""),
        })
    return out


def remove_document(doc_name: str) -> None:
    """Remove all chunks for a document from the vector store."""
    m = _get_client()
    for agent_id in _known_rag_agent_ids():
        try:
            all_mem = m.get_all(agent_id=agent_id)
            if isinstance(all_mem, dict):
                all_mem = all_mem.get("results", [])
            for entry in all_mem:
                if entry.get("metadata", {}).get("doc_name") == doc_name:
                    m.delete(entry["id"])
        except Exception:
            pass


def _known_rag_agent_ids() -> list[str]:
    m = _get_client()
    try:
        all_mem = m.get_all()
        if isinstance(all_mem, dict):
            all_mem = all_mem.get("results", [])
        ids: set[str] = set()
        for entry in all_mem:
            aid = entry.get("agent_id") or entry.get("user_id", "")
            if aid.startswith("rag:"):
                ids.add(aid)
        return list(ids) or [_doc_agent_id("global", None, None)]
    except Exception:
        return [_doc_agent_id("global", None, None)]
