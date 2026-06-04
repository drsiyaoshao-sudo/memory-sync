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

_MACHINE_CONFIG_PATH = GLOBAL_RAW / "machine_config.yaml"
_FALLBACK_LLM = "qwen2.5:0.5b"
_FALLBACK_EMBED = "nomic-embed-text"


def _load_machine_models() -> tuple[str, str]:
    """Read machine_config.yaml and return (llm_model, embed_model) for this hostname."""
    hostname = os.uname().nodename
    try:
        import yaml
        data = yaml.safe_load(_MACHINE_CONFIG_PATH.read_text())
        machines = data.get("machines", {})
        entry = machines.get(hostname) or machines.get("_default") or {}
        return entry.get("llm_model", _FALLBACK_LLM), entry.get("embed_model", _FALLBACK_EMBED)
    except Exception:
        return _FALLBACK_LLM, _FALLBACK_EMBED


def _build_mem0_config() -> dict:
    llm_model, embed_model = _load_machine_models()
    if llm_model.startswith("claude-"):
        llm_block = {
            "provider": "anthropic",
            "config": {"model": llm_model, "temperature": 0, "max_tokens": 2000},
        }
    else:
        llm_block = {
            "provider": "ollama",
            "config": {"model": llm_model, "ollama_base_url": "http://localhost:11434"},
        }
    return {
        "vector_store": {
            "provider": "chroma",
            "config": {"collection_name": "brain", "path": str(GLOBAL_VECTOR)},
        },
        "embedder": {
            "provider": "ollama",
            "config": {"model": embed_model, "ollama_base_url": "http://localhost:11434"},
        },
        "llm": llm_block,
        "history_db_path": str(BRAIN_DIR / "mem0_history.db"),
        "version": "v1.1",
    }


MEM0_CONFIG = _build_mem0_config()


def repo_brain(cwd: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(cwd) / ".brain"


def repo_machine_dir(cwd: str | pathlib.Path) -> pathlib.Path:
    return repo_brain(cwd) / "machine"


def repo_context(cwd: str | pathlib.Path) -> pathlib.Path:
    return repo_brain(cwd) / "context.md"


def ensure_dirs() -> None:
    for d in (GLOBAL_RAW, GLOBAL_ARCHIVE, GLOBAL_KG, GLOBAL_VECTOR):
        d.mkdir(parents=True, exist_ok=True)
