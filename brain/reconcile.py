"""Syncthing conflict resolution + index rebuild for global memory.

Run on UserPromptSubmit hook. Must complete in <500ms.
Only touches ~/.brain/raw/ (global scope). Repo/.brain/ never syncs.

Syncthing conflict filename format:
  <base>.sync-conflict-YYYYMMDD-HHMMSS-DEVICEID<ext>
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import frontmatter  # python-frontmatter

from .config import GLOBAL_ARCHIVE, GLOBAL_RAW, ensure_dirs

CONFLICT_RE = re.compile(
    r"^(.+)\.sync-conflict-(\d{8})-(\d{6})-([A-Z0-9]+)(\..+)$"
)

_HASH_CACHE = GLOBAL_RAW.parent / ".reconcile_hash"


def _mtime_hash(directory: pathlib.Path) -> str:
    """Quick hash of all file mtimes in directory to detect changes."""
    try:
        entries = sorted(directory.glob("*.md"))
        return str(hash(tuple((f.name, f.stat().st_mtime) for f in entries)))
    except Exception:
        return ""


def _read_updated(path: pathlib.Path) -> datetime.datetime | None:
    try:
        post = frontmatter.load(str(path))
        updated_str = post.metadata.get("metadata", {}).get("updated") or post.metadata.get("updated")
        if updated_str:
            return datetime.datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        return datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.UTC)
    except Exception:
        return None


def _archive(path: pathlib.Path, suffix: str = "") -> None:
    GLOBAL_ARCHIVE.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    dest = GLOBAL_ARCHIVE / f"{path.stem}{suffix}_{ts}{path.suffix}"
    path.rename(dest)


def _merge_machines(winner: pathlib.Path, loser: pathlib.Path | None) -> None:
    """Union the machines: lists from both files into the winner."""
    try:
        w_post = frontmatter.load(str(winner))
        w_machines = set(w_post.metadata.get("metadata", {}).get("machines", ["shared"]))
        if loser and loser.exists():
            l_post = frontmatter.load(str(loser))
            l_machines = set(l_post.metadata.get("metadata", {}).get("machines", []))
            merged = sorted(w_machines | l_machines)
            if "metadata" not in w_post.metadata:
                w_post.metadata["metadata"] = {}
            w_post.metadata["metadata"]["machines"] = merged
            winner.write_text(frontmatter.dumps(w_post))
    except Exception:
        pass


def resolve_conflicts() -> int:
    """Resolve all .sync-conflict-* files in ~/.brain/raw/. Returns count resolved."""
    resolved = 0
    if not GLOBAL_RAW.exists():
        return 0

    for conflict_file in GLOBAL_RAW.glob("*.sync-conflict-*"):
        m = CONFLICT_RE.match(conflict_file.name)
        if not m:
            continue
        base_stem, _date, _time, _device, ext = m.groups()
        canonical = GLOBAL_RAW / f"{base_stem}{ext}"

        conflict_updated = _read_updated(conflict_file)
        canonical_updated = _read_updated(canonical) if canonical.exists() else None

        if not canonical.exists():
            conflict_file.rename(canonical)
        elif conflict_updated and canonical_updated and conflict_updated > canonical_updated:
            _archive(canonical, "_canonical_loser")
            _merge_machines(conflict_file, None)
            conflict_file.rename(canonical)
        else:
            _merge_machines(canonical, conflict_file)
            _archive(conflict_file)

        resolved += 1

    return resolved


def _needs_index_rebuild() -> bool:
    """True if raw/ changed since last reconcile run."""
    current_hash = _mtime_hash(GLOBAL_RAW)
    if _HASH_CACHE.exists():
        if _HASH_CACHE.read_text().strip() == current_hash:
            return False
    _HASH_CACHE.write_text(current_hash)
    return True


def rebuild_indexes() -> None:
    """Rebuild KG + Mem0 indexes from ~/.brain/raw/ markdown files."""
    from . import kg, mem, rag

    kg.init()

    for md_file in GLOBAL_RAW.glob("*.md"):
        if md_file.name.startswith("machine_"):
            _index_machine_profile(md_file)
        else:
            _index_memory_file(md_file)


def _index_machine_profile(path: pathlib.Path) -> None:
    from . import kg

    try:
        post = frontmatter.load(str(path))
        meta = post.metadata.get("metadata", {})
        name = post.metadata.get("name", path.stem)
        desc = post.metadata.get("description", "")
        machines = meta.get("machines", ["shared"])
        tag = machines[0] if machines else "shared"
        updated = meta.get("updated", "")
        kg.upsert_machine(name=name, tag=tag, os_str=desc, description=desc, updated=updated)
    except Exception:
        pass


def _index_memory_file(path: pathlib.Path) -> None:
    from . import mem as mem_mod, rag, kg

    try:
        post = frontmatter.load(str(path))
        meta = post.metadata.get("metadata", {})
        status = meta.get("status", "active")
        if status == "archived":
            return
        mem_type = meta.get("type", "project")
        name = post.metadata.get("name", path.stem)
        description = post.metadata.get("description", "")
        content = str(post.content).strip()
        updated = meta.get("updated", "")
        if not content and not description:
            return

        # Add to KG
        kg.upsert_node(
            f"memory:{name}",
            type="Memory",
            name=name,
            description=description,
            mem_type=mem_type,
            updated=updated,
            file=path.name,
        )

        # Add to Mem0 facts
        combined = f"{description} {content}"[:2000].strip()
        mem_mod.remember(
            content=combined,
            agent_id="global",
            metadata={"name": name, "type": mem_type, "file": path.name},
        )

        # Add to RAG vector store
        if content:
            rag.index_document(
                text=content,
                doc_name=name,
                source_path=str(path),
                scope="global",
            )
    except Exception:
        pass


def _probe_if_needed(hostname: str, cwd: str) -> bool:
    """Fire machine probe as background subprocess if profile is missing or stale."""
    from .config import GLOBAL_RAW, PROBE_TTL_DAYS

    profile = GLOBAL_RAW / f"machine_{hostname}.md"
    needs_probe = not profile.exists()
    if not needs_probe and profile.exists():
        try:
            post = frontmatter.load(str(profile))
            updated_str = post.metadata.get("metadata", {}).get("updated")
            if updated_str:
                updated = datetime.datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.UTC) - updated).days
                needs_probe = age >= PROBE_TTL_DAYS
        except Exception:
            needs_probe = True

    if needs_probe:
        subprocess.Popen(
            [sys.executable, "-m", "brain.probe_runner", hostname, cwd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return needs_probe


def main(argv: list[str] | None = None) -> None:
    """Entry point for UserPromptSubmit hook."""
    import argparse
    t_start = time.monotonic()

    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--machine", default=os.uname().nodename)
    args = parser.parse_args(argv)

    ensure_dirs()

    conflicts_resolved = resolve_conflicts()

    probe_launched = _probe_if_needed(args.machine, args.cwd)

    index_rebuilt = False
    if _needs_index_rebuild():
        try:
            rebuild_indexes()
            index_rebuilt = True
        except ImportError:
            pass  # dependencies not installed yet

    elapsed_ms = int((time.monotonic() - t_start) * 1000)

    parts = []
    if conflicts_resolved:
        parts.append(f"{conflicts_resolved} conflict(s) resolved")
    if probe_launched:
        parts.append("machine probe launched")
    if index_rebuilt:
        parts.append("indexes rebuilt")
    status = ", ".join(parts) if parts else "clean"

    print(f"[BRAIN] {args.machine} | {pathlib.Path(args.cwd).name} | {status} ({elapsed_ms}ms)")


if __name__ == "__main__":
    main()
