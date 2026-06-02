"""Session-end flush: extract facts from session, write to all three scopes.

Called by Stop hook as a fire-and-forget subprocess.
Reads Claude Code Stop hook payload from stdin:
  { session_id, stop_hook_active, transcript_path, cwd }

Responsibilities:
1. Update <repo>/.brain/context.md with session summary
2. Extract memory-worthy facts → write to ~/.brain/raw/ (global) or .brain/ (repo)
3. Update Mem0 + KG indexes for any new global facts
4. Track last_accessed on global memories (access_count bump)
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys

import frontmatter

from .config import GLOBAL_RAW, ensure_dirs, repo_brain, repo_context

MEMORY_SIGNALS = re.compile(
    r"\b(remember|forget|decision|decided|project state|machine|sync|context|"
    r"architecture|important|critical|note:|TODO:|FIXME:)\b",
    re.IGNORECASE,
)

FACT_PATTERNS = [
    re.compile(r"(?:remember|note)\s+that\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"decided\s+to\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"important:\s*(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"key\s+(?:insight|decision|fact):\s*(.+?)(?:\.|$)", re.IGNORECASE),
]


def _read_transcript(transcript_path: str | None) -> str:
    if not transcript_path:
        return ""
    try:
        lines = []
        with open(transcript_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    role = entry.get("type", "")
                    if role in ("assistant", "human"):
                        msg = entry.get("message", {})
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text":
                                lines.append(f"{role}: {block['text'][:500]}")
                            elif isinstance(block, str):
                                lines.append(f"{role}: {block[:500]}")
                except Exception:
                    pass
        return "\n".join(lines[-100:])
    except Exception:
        return ""


def _extract_facts(transcript: str) -> list[str]:
    facts = []
    for pattern in FACT_PATTERNS:
        for match in pattern.finditer(transcript):
            fact = match.group(1).strip()
            if len(fact) > 20:
                facts.append(fact)
    return list(dict.fromkeys(facts))[:10]


def _summarize_session(transcript: str, cwd: str) -> str:
    """Build a short context.md summary from transcript tail."""
    project = pathlib.Path(cwd).name
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    lines = [f"# {project} — last session {now[:10]}", ""]

    signal_lines = [
        line for line in transcript.splitlines()
        if MEMORY_SIGNALS.search(line)
    ][-20:]

    if signal_lines:
        lines.append("## Session highlights")
        for l in signal_lines:
            lines.append(f"- {l[:200]}")
    else:
        lines.append("*(no highlighted signals this session)*")

    return "\n".join(lines) + "\n"


def _write_repo_context(cwd: str, transcript: str) -> None:
    brain_dir = repo_brain(cwd)
    brain_dir.mkdir(parents=True, exist_ok=True)
    gitignore = pathlib.Path(cwd) / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".brain/" not in content:
            with gitignore.open("a") as f:
                f.write("\n.brain/\n")
    else:
        gitignore.write_text(".brain/\n")

    summary = _summarize_session(transcript, cwd)
    repo_context(cwd).write_text(summary)


def _write_global_facts(facts: list[str], cwd: str) -> None:
    if not facts:
        return
    ensure_dirs()
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    project = pathlib.Path(cwd).name
    slug = re.sub(r"[^a-z0-9]+", "-", f"session-{project}-{now[:10]}").strip("-")
    path = GLOBAL_RAW / f"session_{slug}.md"

    meta = {
        "name": slug,
        "description": f"Session facts from {project} on {now[:10]}",
        "metadata": {
            "type": "project",
            "machines": ["shared"],
            "updated": now,
            "ttl": "30d",
            "confidence": 0.8,
            "status": "active",
            "last_accessed": now,
            "access_count": 0,
        },
    }

    import yaml
    content = "---\n" + yaml.dump(meta, default_flow_style=False) + "---\n\n"
    content += "\n".join(f"- {f}" for f in facts) + "\n"
    path.write_text(content)

    try:
        from . import mem as mem_mod
        for fact in facts:
            mem_mod.remember(fact, agent_id=f"project:{project}")
    except Exception:
        pass


def _bump_access_counts(cwd: str) -> None:
    """Increment access_count on all active global memories (they were loaded this session)."""
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    if not GLOBAL_RAW.exists():
        return
    for md_file in GLOBAL_RAW.glob("*.md"):
        try:
            post = frontmatter.load(str(md_file))
            meta = post.metadata.get("metadata", {})
            if meta.get("status", "active") != "active":
                continue
            meta["last_accessed"] = now
            meta["access_count"] = int(meta.get("access_count", 0)) + 1
            post.metadata["metadata"] = meta
            md_file.write_text(frontmatter.dumps(post))
        except Exception:
            pass


def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--machine", default=os.uname().nodename)
    args = parser.parse_args(argv)

    raw_stdin = sys.stdin.read()
    payload: dict = {}
    try:
        payload = json.loads(raw_stdin) if raw_stdin.strip().startswith("{") else {}
    except Exception:
        pass

    transcript_path = payload.get("transcript_path")
    cwd = payload.get("cwd", args.cwd)

    transcript = _read_transcript(transcript_path)
    facts = _extract_facts(transcript)

    _write_repo_context(cwd, transcript)
    _write_global_facts(facts, cwd)
    _bump_access_counts(cwd)


if __name__ == "__main__":
    main()
