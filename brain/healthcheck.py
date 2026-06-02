"""Brain pipeline health check.

Checks every layer of the pipeline and prints a structured status report.
Designed to be run standalone (python -m brain.healthcheck) or via `brain health`.

Layers checked:
  1. Raw      — file count, conflicts, staleness, machine profiles
  2. KG       — node/edge count, consistency vs raw
  3. Mem0     — vector store reachable, search returns results
  4. Ollama   — serving, nomic-embed-text available
  5. Syncthing— recent mtime in raw/ suggests sync is alive
  6. Hooks    — settings.json has reconcile + bootstrap + flush wired
  7. MCP      — ~/.claude/.mcp.json points to memory-sync brain
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

from .config import (
    BRAIN_DIR, GLOBAL_RAW, GLOBAL_ARCHIVE, GLOBAL_KG, GLOBAL_VECTOR,
    HOME, PROBE_TTL_DAYS,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _ok(label: str, detail: str = "") -> dict:
    return {"status": "ok", "label": label, "detail": detail}

def _warn(label: str, detail: str = "") -> dict:
    return {"status": "warn", "label": label, "detail": detail}

def _fail(label: str, detail: str = "") -> dict:
    return {"status": "fail", "label": label, "detail": detail}


# ── individual checks ─────────────────────────────────────────────────────────

def check_raw() -> list[dict]:
    results = []
    if not GLOBAL_RAW.exists():
        return [_fail("raw/", "~/.brain/raw/ does not exist")]

    files = list(GLOBAL_RAW.glob("*.md"))
    results.append(_ok("raw/", f"{len(files)} markdown files"))

    conflicts = list(GLOBAL_RAW.glob("*.sync-conflict-*"))
    if conflicts:
        results.append(_warn("conflicts", f"{len(conflicts)} unresolved Syncthing conflicts"))
    else:
        results.append(_ok("conflicts", "none"))

    if files:
        newest_mtime = max(f.stat().st_mtime for f in files)
        age_h = (time.time() - newest_mtime) / 3600
        if age_h > 48:
            results.append(_warn("raw freshness", f"newest file {age_h:.0f}h old — Syncthing sync may be stalled"))
        else:
            results.append(_ok("raw freshness", f"newest file {age_h:.1f}h old"))

    hostname = os.uname().nodename
    machine_file = GLOBAL_RAW / f"machine_{hostname}.md"
    if not machine_file.exists():
        results.append(_warn("machine profile", f"machine_{hostname}.md not in raw/ — run brain_probe"))
    else:
        age_d = (time.time() - machine_file.stat().st_mtime) / 86400
        if age_d > PROBE_TTL_DAYS:
            results.append(_warn("machine profile", f"machine_{hostname}.md is {age_d:.0f}d old (TTL={PROBE_TTL_DAYS}d)"))
        else:
            results.append(_ok("machine profile", f"machine_{hostname}.md ({age_d:.1f}d old)"))

    all_machine_files = list(GLOBAL_RAW.glob("machine_*.md"))
    machine_names = [f.stem.replace("machine_", "") for f in all_machine_files]
    results.append(_ok("known machines", ", ".join(machine_names) if machine_names else "none"))

    return results


def check_kg() -> list[dict]:
    results = []
    graph_path = GLOBAL_KG / "graph.json"
    if not graph_path.exists():
        return [_fail("KG", "graph.json not found — run reconcile to rebuild")]

    try:
        import networkx as nx
        with open(graph_path) as f:
            data = json.load(f)
        G = nx.node_link_graph(data)
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()

        raw_count = len(list(GLOBAL_RAW.glob("*.md")))
        if n_nodes < raw_count // 2:
            results.append(_warn("KG", f"{n_nodes} nodes / {n_edges} edges — fewer than expected vs {raw_count} raw files"))
        else:
            results.append(_ok("KG", f"{n_nodes} nodes / {n_edges} edges"))

        type_dist: dict[str, int] = {}
        for _, attrs in G.nodes(data=True):
            t = attrs.get("mem_type") or attrs.get("node_type", "?")
            type_dist[t] = type_dist.get(t, 0) + 1
        results.append(_ok("KG types", " / ".join(f"{k}:{v}" for k, v in sorted(type_dist.items()))))

    except Exception as e:
        results.append(_fail("KG", str(e)))

    return results


def check_mem0() -> list[dict]:
    results = []
    vector_dir = GLOBAL_VECTOR
    if not vector_dir.exists() or not any(vector_dir.iterdir()):
        return [_fail("Mem0", "vector store empty — run reconcile to rebuild")]

    try:
        from . import mem as mem_mod
        hits = mem_mod.search_all("user", limit=2)
        results.append(_ok("Mem0", f"search reachable, {len(hits)} hits for 'user'"))
    except Exception as e:
        results.append(_fail("Mem0", f"search failed: {e}"))

    return results


def check_ollama() -> list[dict]:
    results = []
    if not shutil.which("ollama"):
        return [_warn("Ollama", "ollama binary not found — embedding will fail")]

    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if any("nomic-embed-text" in m for m in models):
            results.append(_ok("Ollama", f"serving, nomic-embed-text available ({len(models)} models)"))
        else:
            results.append(_warn("Ollama", f"serving but nomic-embed-text not found — run: ollama pull nomic-embed-text"))
    except OSError:
        results.append(_warn("Ollama", "not reachable at localhost:11434 — run: ollama serve"))
    except Exception as e:
        results.append(_warn("Ollama", str(e)))

    return results


def check_syncthing() -> list[dict]:
    results = []
    if not GLOBAL_RAW.exists():
        return [_warn("Syncthing", "~/.brain/raw/ not found")]

    files = list(GLOBAL_RAW.glob("*.md"))
    if not files:
        return [_warn("Syncthing", "raw/ exists but is empty")]

    mtimes = sorted((f.stat().st_mtime, f.name) for f in files)
    newest_ts, newest_name = mtimes[-1]
    age_h = (time.time() - newest_ts) / 3600

    if shutil.which("syncthing"):
        results.append(_ok("Syncthing", "binary found"))
    else:
        results.append(_warn("Syncthing", "binary not in PATH — is it installed?"))

    if age_h < 24:
        results.append(_ok("sync freshness", f"latest file '{newest_name}' written {age_h:.1f}h ago"))
    elif age_h < 72:
        results.append(_warn("sync freshness", f"latest file '{newest_name}' is {age_h:.0f}h old"))
    else:
        results.append(_fail("sync freshness", f"no raw/ update in {age_h:.0f}h — sync may be down"))

    all_machines = [f.stem.replace("machine_", "") for f in GLOBAL_RAW.glob("machine_*.md")]
    if len(all_machines) >= 2:
        results.append(_ok("cross-machine", f"profiles from {len(all_machines)} machines: {', '.join(all_machines)}"))
    else:
        results.append(_warn("cross-machine", f"only 1 machine profile found — other machine not synced yet"))

    return results


def check_hooks() -> list[dict]:
    results = []
    settings_path = HOME / ".claude" / "settings.json"
    if not settings_path.exists():
        return [_warn("hooks", "~/.claude/settings.json not found")]

    try:
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})

        ups_hooks = str(hooks.get("UserPromptSubmit", ""))
        stop_hooks = str(hooks.get("Stop", ""))

        checks = [
            ("reconcile", "brain.reconcile" in ups_hooks),
            ("bootstrap", "brain.bootstrap" in ups_hooks),
            ("flush",     "brain.flush" in stop_hooks),
        ]
        missing = [name for name, found in checks if not found]
        if missing:
            results.append(_warn("hooks", f"missing: {', '.join(missing)}"))
        else:
            results.append(_ok("hooks", "reconcile + bootstrap (UserPromptSubmit) + flush (Stop) all wired"))
    except Exception as e:
        results.append(_warn("hooks", str(e)))

    return results


def check_mcp() -> list[dict]:
    results = []
    mcp_path = HOME / ".claude" / ".mcp.json"
    if not mcp_path.exists():
        return [_fail("MCP", "~/.claude/.mcp.json not found — brain tools unavailable")]

    try:
        cfg = json.loads(mcp_path.read_text())
        servers = cfg.get("mcpServers", {})
        if "brain" not in servers:
            return [_fail("MCP", "brain server not in mcpServers")]

        brain_cfg = servers["brain"]
        cwd = brain_cfg.get("cwd", "")
        expected = str(HOME / "memory-sync")
        if cwd != expected:
            results.append(_warn("MCP", f"cwd={cwd!r} (expected {expected!r})"))
        else:
            results.append(_ok("MCP", f"brain server registered, cwd={cwd}"))
    except Exception as e:
        results.append(_fail("MCP", str(e)))

    return results


# ── report ────────────────────────────────────────────────────────────────────

ICONS = {"ok": "✓", "warn": "⚠", "fail": "✗"}
COLORS = {"ok": "\033[32m", "warn": "\033[33m", "fail": "\033[31m"}
RESET = "\033[0m"


def _fmt(result: dict, color: bool = True) -> str:
    s = result["status"]
    icon = ICONS[s]
    label = result["label"]
    detail = result["detail"]
    line = f"  {icon} {label}" + (f": {detail}" if detail else "")
    if color:
        line = f"{COLORS[s]}{line}{RESET}"
    return line


def run_check(color: bool = True) -> tuple[list[dict], bool]:
    """Run all checks, return (all_results, healthy)."""
    sections = [
        ("Raw storage",  check_raw),
        ("KG (NetworkX)", check_kg),
        ("Mem0 / ChromaDB", check_mem0),
        ("Ollama", check_ollama),
        ("Syncthing", check_syncthing),
        ("Hooks", check_hooks),
        ("MCP server", check_mcp),
    ]

    all_results: list[dict] = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = os.uname().nodename

    print(f"\n[BRAIN HEALTH] {hostname}  {now}")
    print("─" * 50)

    for section, fn in sections:
        results = fn()
        all_results.extend(results)
        print(f"\n{section}")
        for r in results:
            print(_fmt(r, color))

    fails = [r for r in all_results if r["status"] == "fail"]
    warns = [r for r in all_results if r["status"] == "warn"]
    oks   = [r for r in all_results if r["status"] == "ok"]

    print("\n" + "─" * 50)
    summary = f"✓ {len(oks)} ok  ⚠ {len(warns)} warn  ✗ {len(fails)} fail"
    if fails:
        overall = "UNHEALTHY"
        col = COLORS["fail"]
    elif warns:
        overall = "DEGRADED"
        col = COLORS["warn"]
    else:
        overall = "HEALTHY"
        col = COLORS["ok"]

    if color:
        print(f"{col}{overall}{RESET}  {summary}")
    else:
        print(f"{overall}  {summary}")
    print()

    return all_results, not bool(fails)


def main(argv: list[str] | None = None) -> None:
    no_color = "--no-color" in (argv or sys.argv)
    _, healthy = run_check(color=not no_color)
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
