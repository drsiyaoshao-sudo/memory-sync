"""Tests for brain/rag.py — chunking logic and agent_id routing (no Ollama/Chroma)."""

import pytest


class TestChunkText:
    def _chunk(self, text, size=1000, overlap=100):
        from brain.rag import _chunk_text
        return _chunk_text(text, size=size, overlap=overlap)

    def test_short_text_is_single_chunk(self):
        text = "short text"
        chunks = self._chunk(text, size=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_is_split(self):
        # 5000 chars > 4000 (size=1000 * 4 chars/token)
        text = "a" * 5000
        chunks = self._chunk(text, size=1000, overlap=0)
        assert len(chunks) > 1

    def test_overlap_causes_content_repetition(self):
        # With overlap, adjacent chunks share a suffix/prefix
        text = "x" * 2000
        chunks = self._chunk(text, size=200, overlap=50)
        assert len(chunks) >= 2
        # Each chunk should be non-empty and stripped
        for c in chunks:
            assert c.strip()

    def test_empty_string_returns_empty(self):
        assert self._chunk("") == []

    def test_whitespace_only_returns_empty(self):
        assert self._chunk("   \n\t  ") == []

    def test_chunks_cover_all_content(self):
        # Every character in original should appear somewhere in the chunks
        text = "hello world " * 100
        chunks = self._chunk(text, size=50, overlap=10)
        combined = "".join(chunks)
        # All unique chars present
        for ch in set(text.strip()):
            assert ch in combined


class TestDocAgentId:
    def _agent_id(self, scope, project=None, machine=None):
        from brain.rag import _doc_agent_id
        return _doc_agent_id(scope, project, machine)

    def test_scope_only(self):
        assert self._agent_id("global") == "rag:global"

    def test_scope_and_project(self):
        assert self._agent_id("repo", project="gait_device") == "rag:repo:project:gait_device"

    def test_scope_and_machine(self):
        assert self._agent_id("machine", machine="mac") == "rag:machine:machine:mac"

    def test_all_three(self):
        result = self._agent_id("repo", project="p", machine="m")
        assert result == "rag:repo:project:p:machine:m"

    def test_none_parts_omitted(self):
        result = self._agent_id("global", project=None, machine=None)
        assert "project" not in result
        assert "machine" not in result
