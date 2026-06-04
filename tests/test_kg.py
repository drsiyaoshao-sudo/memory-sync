"""Tests for brain/kg.py — NetworkX graph layer."""

import json
import pathlib
import unittest.mock as mock

import pytest


def _isolated_kg(tmp_path: pathlib.Path):
    """Return kg module with graph file redirected to tmp_path."""
    import brain.kg as kg
    kg_dir = tmp_path / "kg"
    kg_dir.mkdir()
    # Reset module-level singleton so each test gets a fresh graph
    kg._G = None
    kg._GRAPH_FILE = None
    with mock.patch("brain.kg._graph_path", return_value=kg_dir / "graph.json"):
        yield kg
    kg._G = None
    kg._GRAPH_FILE = None


@pytest.fixture()
def kg(tmp_path):
    import brain.kg as kg_mod
    kg_dir = tmp_path / "kg"
    kg_dir.mkdir()
    kg_mod._G = None
    kg_mod._GRAPH_FILE = None
    graph_file = kg_dir / "graph.json"
    with mock.patch("brain.kg._graph_path", return_value=graph_file):
        kg_mod.init()
        yield kg_mod
    kg_mod._G = None


class TestUpsertNode:
    def test_add_new_node(self, kg):
        kg.upsert_node("test:foo", type="Memory", name="foo", description="bar")
        nodes = kg.all_nodes()
        ids = [n["node_id"] for n in nodes]
        assert "test:foo" in ids

    def test_update_existing_node(self, kg):
        kg.upsert_node("test:foo", type="Memory", name="foo")
        kg.upsert_node("test:foo", description="updated")
        nodes = {n["node_id"]: n for n in kg.all_nodes()}
        assert nodes["test:foo"]["description"] == "updated"
        assert nodes["test:foo"]["name"] == "foo"

    def test_graph_persists_to_disk(self, kg, tmp_path):
        kg.upsert_node("test:persist", type="Memory", name="persist")
        graph_files = list((tmp_path / "kg").glob("*.json"))
        assert graph_files, "graph.json should exist after upsert"
        data = json.loads(graph_files[0].read_text())
        node_ids = [n["id"] for n in data["nodes"]]
        assert "test:persist" in node_ids


class TestUpsertEdge:
    def test_add_edge_creates_missing_nodes(self, kg):
        kg.upsert_edge("proj:alpha", "machine:mac", "RUNS_ON")
        assert kg._g().has_node("proj:alpha")
        assert kg._g().has_node("machine:mac")
        assert kg._g().has_edge("proj:alpha", "machine:mac")

    def test_edge_rel_attribute(self, kg):
        kg.upsert_edge("a", "b", "DEPENDS_ON", weight=2)
        edge = kg._g().edges["a", "b"]
        assert edge["rel"] == "DEPENDS_ON"
        assert edge["weight"] == 2


class TestUpsertMachine:
    def test_machine_node_type(self, kg):
        kg.upsert_machine("machine-mac", "mac", "Darwin arm64", "Mac M1", "2026-01-01")
        nodes = {n["node_id"]: n for n in kg.all_nodes("Machine")}
        assert "machine:machine-mac" in nodes
        assert nodes["machine:machine-mac"]["type"] == "Machine"
        assert nodes["machine:machine-mac"]["tag"] == "mac"


class TestAllNodes:
    def test_filter_by_type(self, kg):
        kg.upsert_node("mem:a", type="Memory", name="a")
        kg.upsert_node("mac:b", type="Machine", name="b")
        memories = kg.all_nodes("Memory")
        machines = kg.all_nodes("Machine")
        assert all(n["type"] == "Memory" for n in memories)
        assert all(n["type"] == "Machine" for n in machines)

    def test_no_filter_returns_all(self, kg):
        kg.upsert_node("x:1", type="A")
        kg.upsert_node("x:2", type="B")
        assert len(kg.all_nodes()) >= 2


class TestGraphSearch:
    def test_finds_by_description_substring(self, kg):
        kg.upsert_node("mem:gait", type="Memory", description="gait device simulation pipeline")
        results = kg.graph_search("gait device")
        assert any(r["node_id"] == "mem:gait" for r in results)

    def test_no_match_returns_empty(self, kg):
        kg.upsert_node("mem:foo", type="Memory", description="something unrelated")
        assert kg.graph_search("zzznomatch") == []

    def test_filter_by_node_type(self, kg):
        kg.upsert_node("mem:a", type="Memory", description="alpha")
        kg.upsert_node("mac:a", type="Machine", description="alpha machine")
        results = kg.graph_search("alpha", node_type="Memory")
        assert all(r.get("type") == "Memory" for r in results)


class TestGraphNeighbors:
    def test_returns_connected_nodes(self, kg):
        kg.upsert_node("proj:p1", type="Project", name="p1")
        kg.upsert_node("machine:m1", type="Machine", name="m1")
        kg.upsert_edge("proj:p1", "machine:m1", "RUNS_ON")
        neighbors = kg.graph_neighbors("proj:p1")
        assert any(n["node"] == "machine:m1" for n in neighbors)

    def test_filter_by_rel(self, kg):
        kg.upsert_edge("a", "b", "RUNS_ON")
        kg.upsert_edge("a", "c", "DEPENDS_ON")
        runs_on = kg.graph_neighbors("a", rel="RUNS_ON")
        assert all(n["rel"] == "RUNS_ON" for n in runs_on)
        assert not any(n["node"] == "c" for n in runs_on)


class TestProjectsOnMachine:
    def test_returns_projects_linked_to_machine(self, kg):
        kg.upsert_node("machine:mac", type="Machine", tag="mac", name="mac")
        kg.upsert_node("project:gait", type="Project", name="gait")
        kg.upsert_edge("project:gait", "machine:mac", "RUNS_ON")
        projects = kg.projects_on_machine("mac")
        assert "gait" in projects

    def test_wrong_tag_returns_empty(self, kg):
        kg.upsert_node("machine:mac", type="Machine", tag="mac", name="mac")
        kg.upsert_node("project:gait", type="Project", name="gait")
        kg.upsert_edge("project:gait", "machine:mac", "RUNS_ON")
        assert kg.projects_on_machine("linux") == []


class TestRemoveDocument:
    def test_removes_node(self, kg):
        kg.upsert_document("spec", "/path/spec.pdf", "repo", 3, "spec summary", "2026-01-01")
        assert kg._g().has_node("doc:spec")
        kg.remove_document("spec")
        assert not kg._g().has_node("doc:spec")
