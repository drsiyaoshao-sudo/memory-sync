"""Central config: paths and constants derived from the environment."""

import os
import pathlib

HOME = pathlib.Path.home()
BRAIN_DIR = HOME / ".brain"
GLOBAL_RAW = BRAIN_DIR / "raw"
GLOBAL_ARCHIVE = BRAIN_DIR / "archive"
GLOBAL_KG = BRAIN_DIR / "kg"
GLOBAL_VECTOR = BRAIN_DIR / "vector"

DORMANT_AFTER_DAYS = 30
ARCHIVE_AFTER_DAYS = 90
PROBE_TTL_DAYS = 14
ACCESS_COUNT_PROTECTED = 10

PROTECTED_TYPES = {"user", "feedback"}

MEM0_CONFIG = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "brain",
            "path": str(GLOBAL_VECTOR),
        },
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",
            "ollama_base_url": "http://localhost:11434",
        },
    },
    "llm": {
        "provider": "anthropic",
        "config": {
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0,
            "max_tokens": 2000,
        },
    },
    "history_db_path": str(BRAIN_DIR / "mem0_history.db"),
    "version": "v1.1",
}


def repo_brain(cwd: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(cwd) / ".brain"


def repo_machine_dir(cwd: str | pathlib.Path) -> pathlib.Path:
    return repo_brain(cwd) / "machine"


def repo_context(cwd: str | pathlib.Path) -> pathlib.Path:
    return repo_brain(cwd) / "context.md"


def ensure_dirs() -> None:
    for d in (GLOBAL_RAW, GLOBAL_ARCHIVE, GLOBAL_KG, GLOBAL_VECTOR):
        d.mkdir(parents=True, exist_ok=True)
