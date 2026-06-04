"""Tests for brain/flush.py — fact extraction and session summarization."""

import pytest


class TestExtractFacts:
    def _extract(self, text):
        from brain.flush import _extract_facts
        return _extract_facts(text)

    def test_remember_that_pattern(self):
        facts = self._extract("You should remember that the KG uses NetworkX for graph storage.")
        assert any("KG uses NetworkX" in f for f in facts)

    def test_decided_to_pattern(self):
        facts = self._extract("We decided to use Ollama for local embeddings.")
        assert any("use Ollama for local embeddings" in f for f in facts)

    def test_important_pattern(self):
        facts = self._extract("Important: always use hub-and-spoke for Syncthing.")
        assert any("always use hub-and-spoke" in f for f in facts)

    def test_key_decision_pattern(self):
        facts = self._extract("Key decision: federated architecture over centralized.")
        assert any("federated architecture" in f for f in facts)

    def test_short_matches_ignored(self):
        # < 20 chars should not be extracted
        facts = self._extract("Remember that yes.")
        assert not any(len(f) < 20 for f in facts)

    def test_no_patterns_returns_empty(self):
        facts = self._extract("This is just a normal conversation about coding.")
        assert facts == []

    def test_deduplication(self):
        text = (
            "Remember that the cache prefix must be byte-identical. "
            "Remember that the cache prefix must be byte-identical."
        )
        facts = self._extract(text)
        assert len(facts) == len(set(facts))

    def test_capped_at_ten(self):
        lines = [f"Remember that fact number {i} is important for the system." for i in range(20)]
        facts = self._extract(" ".join(lines))
        assert len(facts) <= 10


class TestSummarizeSession:
    def _summarize(self, transcript, project="my_project", tmp_path=None):
        from brain.flush import _summarize_session
        import tempfile, pathlib
        cwd = tmp_path or tempfile.mkdtemp()
        return _summarize_session(transcript, str(cwd))

    def test_includes_project_name(self, tmp_path):
        result = self._summarize("nothing special", tmp_path=tmp_path)
        project = tmp_path.name
        assert project in result

    def test_highlights_memory_signal_lines(self, tmp_path):
        transcript = "assistant: we decided to use Ollama\nhuman: sounds good"
        result = self._summarize(transcript, tmp_path=tmp_path)
        assert "decided" in result

    def test_no_signals_shows_placeholder(self, tmp_path):
        result = self._summarize("assistant: hello\nhuman: hi", tmp_path=tmp_path)
        assert "no highlighted signals" in result

    def test_signal_lines_capped_in_output(self, tmp_path):
        # 30 signal lines — should only keep last 20
        lines = [f"assistant: remember that ITEM_{i:03d} is critical for the pipeline" for i in range(30)]
        transcript = "\n".join(lines)
        result = self._summarize(transcript, tmp_path=tmp_path)
        # Zero-padded IDs have no substring overlap: ITEM_001 is not in ITEM_010
        count = sum(1 for i in range(30) if f"ITEM_{i:03d}" in result)
        assert count <= 20
