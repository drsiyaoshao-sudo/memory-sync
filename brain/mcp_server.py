"""MCP server exposing mcp__brain__* tools globally.

Registered in ~/.claude/claude_desktop_config.json (or settings.json mcp section)
so every Claude Code session — regardless of which repo it opens — has access.

Tools:
  brain_query(q, scope, project, machine, limit)   RAG semantic search
  brain_graph(cypher, params)                       KG Cypher traversal
  brain_mem(q, agent_id, limit)                    Mem0 fact search
  brain_remember(content, agent_id, metadata)       Write a fact to Mem0
  brain_forget(name, scope)                         Archive + deindex a memory
  brain_ingest(path, scope, project, machine, ttl)  Ingest a file/dir
  brain_probe(cwd)                                  Run machine probe now
  brain_read_doc(doc_name)                          Return full source of ingested doc
  brain_project_context(cwd)                        Return .brain/context.md for a repo
  brain_list(scope, project, limit)                 List indexed memories
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


app = Server("brain")


def _tool(name: str, description: str, props: dict, required: list[str] | None = None):
    return types.Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": props,
            "required": required or [],
        },
    )


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        _tool("brain_query",
              "Semantic RAG search over indexed documents. Returns relevant chunks with source attribution.",
              {
                  "q": {"type": "string", "description": "Search query"},
                  "scope": {"type": "string", "description": "Filter scope: global | repo | machine"},
                  "project": {"type": "string", "description": "Filter by project name"},
                  "machine": {"type": "string", "description": "Filter by machine tag (mac/linux)"},
                  "limit": {"type": "integer", "description": "Max results (default 5)"},
              }, ["q"]),

        _tool("brain_graph",
              "Knowledge graph Cypher traversal. Returns structured relationship data.",
              {
                  "cypher": {"type": "string", "description": "Cypher query"},
                  "params": {"type": "object", "description": "Query parameters"},
              }, ["cypher"]),

        _tool("brain_mem",
              "Mem0 fact search. Returns short-form facts matching the query.",
              {
                  "q": {"type": "string", "description": "Search query"},
                  "agent_id": {"type": "string",
                               "description": "Scope: global | project:<name> | machine:<hostname>"},
                  "limit": {"type": "integer", "description": "Max results (default 5)"},
              }, ["q"]),

        _tool("brain_remember",
              "Store a new fact in Mem0.",
              {
                  "content": {"type": "string", "description": "Fact to remember"},
                  "agent_id": {"type": "string",
                               "description": "Scope: global | project:<name> | machine:<hostname>"},
                  "metadata": {"type": "object", "description": "Optional metadata"},
              }, ["content", "agent_id"]),

        _tool("brain_forget",
              "Archive + deindex a memory (moves raw to archive/, removes from KG + Mem0).",
              {
                  "name": {"type": "string", "description": "Memory name slug or doc_name"},
                  "scope": {"type": "string", "description": "global | repo"},
              }, ["name"]),

        _tool("brain_ingest",
              "Ingest a file or directory into the brain (chunk, embed, index in KG + Mem0).",
              {
                  "path": {"type": "string", "description": "Absolute path to file or directory"},
                  "scope": {"type": "string", "description": "global | repo (default: repo)"},
                  "project": {"type": "string", "description": "Project name for scoping"},
                  "machine": {"type": "string", "description": "Machine tag (mac/linux)"},
                  "ttl": {"type": "string", "description": "Time-to-live e.g. 30d (optional)"},
                  "cwd": {"type": "string", "description": "Repo root for repo-scoped ingest"},
              }, ["path"]),

        _tool("brain_probe",
              "Run machine capability probe now. Updates machine profile in global memory.",
              {
                  "cwd": {"type": "string", "description": "Current repo directory (optional)"},
              }, []),

        _tool("brain_read_doc",
              "Return the full source text of an ingested document.",
              {
                  "doc_name": {"type": "string", "description": "Document name slug"},
              }, ["doc_name"]),

        _tool("brain_project_context",
              "Return the .brain/context.md for a repo (last session summary).",
              {
                  "cwd": {"type": "string", "description": "Repo root path"},
              }, ["cwd"]),

        _tool("brain_list",
              "List indexed memories with metadata.",
              {
                  "scope": {"type": "string", "description": "global | repo | all"},
                  "project": {"type": "string", "description": "Filter by project"},
                  "limit": {"type": "integer", "description": "Max results (default 20)"},
              }, []),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def _dispatch(name: str, args: dict) -> Any:
    loop = asyncio.get_event_loop()

    if name == "brain_query":
        from . import rag
        return await loop.run_in_executor(None, lambda: rag.query(
            q=args["q"],
            scope=args.get("scope"),
            project=args.get("project"),
            machine=args.get("machine"),
            limit=args.get("limit", 5),
        ))

    elif name == "brain_graph":
        from . import kg
        rows = await loop.run_in_executor(None, lambda: kg.query(
            args["cypher"], args.get("params")
        ))
        return {"rows": rows, "count": len(rows)}

    elif name == "brain_mem":
        from . import mem as mem_mod
        agent_id = args.get("agent_id")
        if agent_id:
            results = await loop.run_in_executor(None, lambda: mem_mod.search(
                args["q"], agent_id=agent_id, limit=args.get("limit", 5)
            ))
        else:
            results = await loop.run_in_executor(None, lambda: mem_mod.search_all(
                args["q"], limit=args.get("limit", 5)
            ))
        return {"results": results, "count": len(results)}

    elif name == "brain_remember":
        from . import mem as mem_mod
        mem_id = await loop.run_in_executor(None, lambda: mem_mod.remember(
            content=args["content"],
            agent_id=args["agent_id"],
            metadata=args.get("metadata"),
        ))
        return {"id": mem_id, "status": "stored"}

    elif name == "brain_forget":
        return await _handle_forget(args, loop)

    elif name == "brain_ingest":
        from . import ingest as ingest_mod
        result = await loop.run_in_executor(None, lambda: ingest_mod.ingest(
            path=args["path"],
            scope=args.get("scope", "repo"),
            project=args.get("project"),
            machine=args.get("machine"),
            ttl=args.get("ttl"),
            cwd=args.get("cwd"),
        ))
        return result

    elif name == "brain_probe":
        from . import probe
        cwd = args.get("cwd") or os.getcwd()
        hostname = os.uname().nodename
        data = await loop.run_in_executor(None, lambda: probe.run(hostname=hostname, cwd=cwd))
        return {"hostname": data["identity"]["hostname"], "tools": len(data["tools"]),
                "status": "profile updated"}

    elif name == "brain_read_doc":
        return await _handle_read_doc(args["doc_name"], loop)

    elif name == "brain_project_context":
        from .config import repo_context
        ctx = repo_context(args["cwd"])
        if ctx.exists():
            return {"cwd": args["cwd"], "context": ctx.read_text()}
        return {"cwd": args["cwd"], "context": None, "note": "No .brain/context.md yet"}

    elif name == "brain_list":
        return await _handle_list(args, loop)

    return {"error": f"unknown tool: {name}"}


async def _handle_forget(args: dict, loop) -> dict:
    from . import kg, rag
    from .config import GLOBAL_RAW, GLOBAL_ARCHIVE
    import datetime

    name = args["name"]
    scope = args.get("scope", "global")

    rag.remove_document(name)
    kg.remove_document(name)

    if scope == "global":
        raw_file = GLOBAL_RAW / f"{name}.md"
        if not raw_file.exists():
            raw_file = next(GLOBAL_RAW.glob(f"*{name}*.md"), None)
        if raw_file and raw_file.exists():
            GLOBAL_ARCHIVE.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
            raw_file.rename(GLOBAL_ARCHIVE / f"{raw_file.stem}_{ts}{raw_file.suffix}")
            return {"status": "archived", "name": name}

    return {"status": "deindexed", "name": name, "note": "raw file not found in global scope"}


async def _handle_read_doc(doc_name: str, loop) -> dict:
    from .config import GLOBAL_RAW
    import glob as glob_mod

    candidates = list(GLOBAL_RAW.glob(f"*{doc_name}*.md"))
    if not candidates:
        return {"error": f"doc '{doc_name}' not found in global raw"}

    path = candidates[0]
    source_path_hint = None
    try:
        import frontmatter
        post = frontmatter.load(str(path))
        source_path_hint = post.metadata.get("metadata", {}).get("source_path")
    except Exception:
        pass

    if source_path_hint and pathlib.Path(source_path_hint).exists():
        text = pathlib.Path(source_path_hint).read_text(errors="replace")
        return {"doc_name": doc_name, "source_path": source_path_hint, "text": text[:50000]}

    return {"doc_name": doc_name, "stub": path.read_text()}


async def _handle_list(args: dict, loop) -> dict:
    from . import mem as mem_mod
    from .config import GLOBAL_RAW

    limit = args.get("limit", 20)
    scope = args.get("scope", "all")
    project = args.get("project")

    memories = []
    if scope in ("global", "all") and GLOBAL_RAW.exists():
        for md_file in sorted(GLOBAL_RAW.glob("*.md"))[:limit]:
            try:
                import frontmatter
                post = frontmatter.load(str(md_file))
                meta = post.metadata.get("metadata", {})
                memories.append({
                    "name": post.metadata.get("name", md_file.stem),
                    "description": post.metadata.get("description", ""),
                    "type": meta.get("type", "?"),
                    "status": meta.get("status", "active"),
                    "updated": meta.get("updated", ""),
                    "scope": "global",
                })
            except Exception:
                pass

    return {"memories": memories[:limit], "count": len(memories)}


def run() -> None:
    from .config import ensure_dirs
    from . import kg
    ensure_dirs()
    kg.init()
    asyncio.run(_serve())


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    run()
