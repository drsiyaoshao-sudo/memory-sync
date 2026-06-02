"""brain CLI entry point.

Usage:
  python -m brain.reconcile --cwd <path> --machine <hostname>
  python -m brain.bootstrap --cwd <path> --machine <hostname>
  python -m brain.flush --cwd <path> --machine <hostname>
  python -m brain.mcp_server   (MCP server, called by Claude config)

Direct invocations (via pyproject.toml [project.scripts]):
  brain reconcile
  brain bootstrap
  brain flush
  brain probe
  brain mcp
"""

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: brain <reconcile|bootstrap|flush|probe|mcp>")
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "reconcile":
        from .reconcile import main as run
        run(rest)
    elif cmd == "bootstrap":
        from .bootstrap import main as run
        run(rest)
    elif cmd == "flush":
        from .flush import main as run
        run(rest)
    elif cmd == "probe":
        from .probe import run as probe_run
        import os
        hostname = rest[0] if rest else os.uname().nodename
        cwd = rest[1] if len(rest) > 1 else os.getcwd()
        data = probe_run(hostname=hostname, cwd=cwd)
        print(f"[BRAIN] probe complete: {data['identity']['hostname']} — {len(data['tools'])} tools")
    elif cmd == "mcp":
        from .mcp_server import run as mcp_run
        mcp_run()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
