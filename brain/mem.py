"""Mem0 facts layer: short-form user/feedback/project memories.

agent_id convention:
  "global"              — cross-machine shared facts (user profile, feedback)
  "machine:<hostname>"  — machine-specific facts
  "project:<name>"      — project-specific facts
  "repo:<path>"         — facts from a specific repo session
"""

from __future__ import annotations

from typing import Any

from .config import MEM0_CONFIG, ensure_dirs

_client = None


def _get_client():
    global _client
    if _client is None:
        ensure_dirs()
        from mem0 import Memory
        _client = Memory.from_config(MEM0_CONFIG)
    return _client


def remember(content: str, agent_id: str, metadata: dict[str, Any] | None = None) -> str:
    """Store a fact. Returns the memory ID."""
    m = _get_client()
    result = m.add(content, agent_id=agent_id, metadata=metadata or {})
    if isinstance(result, list) and result:
        return result[0].get("id", "")
    return ""


def search(query: str, agent_id: str, limit: int = 5) -> list[dict]:
    """Semantic search over facts for a given agent_id scope."""
    m = _get_client()
    results = m.search(query, agent_id=agent_id, limit=limit)
    if isinstance(results, dict):
        results = results.get("results", [])
    return results


def search_all(query: str, limit: int = 10) -> list[dict]:
    """Search across all agent_id scopes. Merges results, deduped by id."""
    m = _get_client()
    all_results: list[dict] = []
    seen: set[str] = set()

    for scope in _known_agent_ids():
        try:
            hits = m.search(query, agent_id=scope, limit=limit)
            if isinstance(hits, dict):
                hits = hits.get("results", [])
            for h in hits:
                mid = h.get("id", "")
                if mid not in seen:
                    seen.add(mid)
                    h["agent_id"] = scope
                    all_results.append(h)
        except Exception:
            pass

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:limit]


def get_all(agent_id: str) -> list[dict]:
    """Return all stored facts for an agent_id (no semantic filter)."""
    m = _get_client()
    result = m.get_all(agent_id=agent_id)
    if isinstance(result, dict):
        return result.get("results", [])
    return result or []


def forget(memory_id: str) -> None:
    m = _get_client()
    m.delete(memory_id)


def forget_all(agent_id: str) -> None:
    m = _get_client()
    m.delete_all(agent_id=agent_id)


def _known_agent_ids() -> list[str]:
    """Best-effort list of agent_ids present in the store."""
    m = _get_client()
    try:
        all_mem = m.get_all()
        if isinstance(all_mem, dict):
            all_mem = all_mem.get("results", [])
        ids: set[str] = set()
        for entry in all_mem:
            aid = entry.get("agent_id") or entry.get("user_id", "global")
            ids.add(aid)
        return list(ids) or ["global"]
    except Exception:
        return ["global"]
