"""Tests for brain/config.py — machine_config.yaml routing."""

import os
import pathlib
import textwrap
import unittest.mock as mock

import pytest
import yaml


def _write_config(tmp_path: pathlib.Path, machines: dict) -> pathlib.Path:
    p = tmp_path / "machine_config.yaml"
    p.write_text(yaml.dump({"machines": machines}))
    return p


def _call_load(config_path: pathlib.Path, hostname: str) -> tuple[str, str]:
    """Call _load_machine_models with a patched YAML path and hostname."""
    import brain.config as cfg
    with mock.patch.object(cfg, "_MACHINE_CONFIG_PATH", config_path), \
         mock.patch("os.uname", return_value=mock.Mock(nodename=hostname)):
        return cfg._load_machine_models()


class TestLoadMachineModels:
    def test_known_hostname_returns_correct_models(self, tmp_path):
        p = _write_config(tmp_path, {
            "my-machine": {"llm_model": "gemma3:12b", "embed_model": "nomic-embed-text"},
            "_default": {"llm_model": "qwen2.5:0.5b", "embed_model": "nomic-embed-text"},
        })
        llm, embed = _call_load(p, "my-machine")
        assert llm == "gemma3:12b"
        assert embed == "nomic-embed-text"

    def test_unknown_hostname_falls_back_to_default(self, tmp_path):
        p = _write_config(tmp_path, {
            "_default": {"llm_model": "qwen2.5:0.5b", "embed_model": "nomic-embed-text"},
        })
        llm, embed = _call_load(p, "unknown-box")
        assert llm == "qwen2.5:0.5b"

    def test_missing_config_file_returns_fallback(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        llm, embed = _call_load(missing, "any-host")
        assert llm == "qwen2.5:0.5b"
        assert embed == "nomic-embed-text"

    def test_malformed_yaml_returns_fallback(self, tmp_path):
        p = tmp_path / "machine_config.yaml"
        p.write_text(": : : invalid yaml {{{{")
        llm, embed = _call_load(p, "any-host")
        assert llm == "qwen2.5:0.5b"

    def test_no_default_and_unknown_hostname_returns_fallback(self, tmp_path):
        p = _write_config(tmp_path, {
            "other-machine": {"llm_model": "llama3:8b", "embed_model": "nomic-embed-text"},
        })
        llm, embed = _call_load(p, "unknown-box")
        assert llm == "qwen2.5:0.5b"


class TestBuildMem0Config:
    def _build(self, tmp_path, hostname, machines):
        p = _write_config(tmp_path, machines)
        import brain.config as cfg
        with mock.patch.object(cfg, "_MACHINE_CONFIG_PATH", p), \
             mock.patch("os.uname", return_value=mock.Mock(nodename=hostname)):
            return cfg._build_mem0_config()

    def test_ollama_model_uses_ollama_provider(self, tmp_path):
        cfg = self._build(tmp_path, "h", {"h": {"llm_model": "gemma3:12b", "embed_model": "nomic-embed-text"}})
        assert cfg["llm"]["provider"] == "ollama"
        assert cfg["llm"]["config"]["model"] == "gemma3:12b"

    def test_claude_model_uses_anthropic_provider(self, tmp_path):
        cfg = self._build(tmp_path, "h", {"h": {"llm_model": "claude-haiku-4-5-20251001", "embed_model": "nomic-embed-text"}})
        assert cfg["llm"]["provider"] == "anthropic"
        assert cfg["llm"]["config"]["model"] == "claude-haiku-4-5-20251001"

    def test_embed_model_always_ollama(self, tmp_path):
        cfg = self._build(tmp_path, "h", {"h": {"llm_model": "gemma3:12b", "embed_model": "all-minilm"}})
        assert cfg["embedder"]["provider"] == "ollama"
        assert cfg["embedder"]["config"]["model"] == "all-minilm"

    def test_vector_store_is_chroma(self, tmp_path):
        cfg = self._build(tmp_path, "h", {"_default": {"llm_model": "qwen2.5:0.5b", "embed_model": "nomic-embed-text"}})
        assert cfg["vector_store"]["provider"] == "chroma"

    def test_anthropic_config_has_temperature_and_max_tokens(self, tmp_path):
        cfg = self._build(tmp_path, "h", {"h": {"llm_model": "claude-haiku-4-5-20251001", "embed_model": "nomic-embed-text"}})
        assert "temperature" in cfg["llm"]["config"]
        assert "max_tokens" in cfg["llm"]["config"]
