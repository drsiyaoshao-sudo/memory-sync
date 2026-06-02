"""Session bootstrap: inject 1-line briefing into Claude Code context.

Output format:
  [BRAIN] <machine> | <project> | mcp__brain__query / graph / mem / remember / forget / ingest

Also performs lightweight context checks:
  - Is this a new project (no .brain/context.md)?
  - Did global memory change since last session?
  - Does the project have a .brain/ with a context.md to surface?
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from .config import GLOBAL_RAW, repo_brain, repo_context


def _project_name(cwd: str) -> str:
    return pathlib.Path(cwd).name or "home"


def _machine_label(hostname: str) -> str:
    """Short human-readable machine label."""
    import platform
    arch = platform.machine()
    os_name = platform.system()
    if os_name == "Darwin":
        return f"Mac {arch}"
    return f"Linux {arch}"


def _get_project_hint(cwd: str) -> str | None:
    """Return a short hint from .brain/context.md if it exists."""
    ctx = repo_context(cwd)
    if not ctx.exists():
        return None
    try:
        text = ctx.read_text().strip()
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
    except Exception:
        pass
    return None


def _check_new_repo(cwd: str) -> bool:
    return not repo_brain(cwd).exists()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--machine", default=os.uname().nodename)
    args = parser.parse_args(argv)

    machine_label = _machine_label(args.machine)
    project = _project_name(args.cwd)
    tools = "mcp__brain__query / graph / mem / remember / forget / ingest"

    line = f"[BRAIN] {machine_label} | {project} | {tools}"

    hint = _get_project_hint(args.cwd)
    if hint:
        line += f"\n[BRAIN] last: {hint}"

    if _check_new_repo(args.cwd):
        line += f"\n[BRAIN] new repo — run mcp__brain__probe to register machine context"

    print(line)


if __name__ == "__main__":
    main()
