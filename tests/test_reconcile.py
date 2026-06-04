"""Tests for brain/reconcile.py — conflict resolution and index rebuild detection."""

import datetime
import pathlib
import shutil
import unittest.mock as mock

import frontmatter
import pytest


def _make_md(path: pathlib.Path, name: str, updated: str, content: str = "body") -> None:
    meta = {
        "name": name,
        "metadata": {
            "type": "project",
            "updated": updated,
            "status": "active",
            "machines": ["mac"],
        },
    }
    post = frontmatter.Post(content, **meta)
    path.write_text(frontmatter.dumps(post))


@pytest.fixture()
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


@pytest.fixture()
def archive_dir(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return d


def _patch_dirs(raw_dir, archive_dir):
    import brain.reconcile as rec
    return mock.patch.multiple(
        "brain.reconcile",
        GLOBAL_RAW=raw_dir,
        GLOBAL_ARCHIVE=archive_dir,
    )


class TestResolveConflicts:
    def test_newer_conflict_wins(self, raw_dir, archive_dir):
        canonical = raw_dir / "project_foo.md"
        conflict = raw_dir / "project_foo.sync-conflict-20260602-120000-ABCDEF.md"
        _make_md(canonical, "project-foo", "2026-06-01T00:00:00Z")
        _make_md(conflict, "project-foo", "2026-06-02T00:00:00Z", content="newer")

        import brain.reconcile as rec
        with _patch_dirs(raw_dir, archive_dir):
            count = rec.resolve_conflicts()

        assert count == 1
        assert canonical.exists()
        assert canonical.read_text().strip().endswith("newer")
        assert not conflict.exists()
        assert any(archive_dir.glob("project_foo_canonical_loser_*.md"))

    def test_older_conflict_is_archived(self, raw_dir, archive_dir):
        canonical = raw_dir / "project_bar.md"
        conflict = raw_dir / "project_bar.sync-conflict-20260601-000000-XYZABC.md"
        _make_md(canonical, "project-bar", "2026-06-03T00:00:00Z", content="canonical wins")
        _make_md(conflict, "project-bar", "2026-06-01T00:00:00Z")

        import brain.reconcile as rec
        with _patch_dirs(raw_dir, archive_dir):
            count = rec.resolve_conflicts()

        assert count == 1
        assert canonical.exists()
        assert "canonical wins" in canonical.read_text()
        assert not conflict.exists()
        assert any(archive_dir.glob("project_bar.sync-conflict-*"))

    def test_no_conflicts_returns_zero(self, raw_dir, archive_dir):
        (raw_dir / "project_clean.md").write_text("---\nname: clean\n---\nbody")
        import brain.reconcile as rec
        with _patch_dirs(raw_dir, archive_dir):
            assert rec.resolve_conflicts() == 0

    def test_conflict_no_canonical_renames_to_canonical(self, raw_dir, archive_dir):
        conflict = raw_dir / "project_new.sync-conflict-20260602-090000-DEVICE1.md"
        _make_md(conflict, "project-new", "2026-06-02T00:00:00Z", content="orphan conflict")

        import brain.reconcile as rec
        with _patch_dirs(raw_dir, archive_dir):
            count = rec.resolve_conflicts()

        assert count == 1
        assert (raw_dir / "project_new.md").exists()
        assert not conflict.exists()

    def test_machines_list_merged_into_winner(self, raw_dir, archive_dir):
        canonical = raw_dir / "project_shared.md"
        conflict = raw_dir / "project_shared.sync-conflict-20260602-100000-AABBCC.md"
        _make_md(canonical, "project-shared", "2026-06-01T00:00:00Z")
        # Give conflict a newer timestamp and a different machine tag
        meta = {
            "name": "project-shared",
            "metadata": {
                "type": "project",
                "updated": "2026-06-02T00:00:00Z",
                "status": "active",
                "machines": ["linux"],
            },
        }
        post = frontmatter.Post("body", **meta)
        conflict.write_text(frontmatter.dumps(post))

        import brain.reconcile as rec
        with _patch_dirs(raw_dir, archive_dir):
            rec.resolve_conflicts()

        result = frontmatter.load(str(canonical))
        machines = result.metadata.get("metadata", {}).get("machines", [])
        assert set(machines) == {"mac", "linux"}


class TestNeedsIndexRebuild:
    def test_first_run_always_rebuilds(self, tmp_path, raw_dir):
        hash_cache = tmp_path / ".reconcile_hash"
        import brain.reconcile as rec
        with mock.patch.object(rec, "_HASH_CACHE", hash_cache), \
             mock.patch("brain.reconcile.GLOBAL_RAW", raw_dir):
            assert rec._needs_index_rebuild() is True

    def test_no_change_skips_rebuild(self, tmp_path, raw_dir):
        (raw_dir / "a.md").write_text("content")
        hash_cache = tmp_path / ".reconcile_hash"
        import brain.reconcile as rec
        with mock.patch.object(rec, "_HASH_CACHE", hash_cache), \
             mock.patch("brain.reconcile.GLOBAL_RAW", raw_dir):
            rec._needs_index_rebuild()  # prime cache
            assert rec._needs_index_rebuild() is False

    def test_new_file_triggers_rebuild(self, tmp_path, raw_dir):
        hash_cache = tmp_path / ".reconcile_hash"
        import brain.reconcile as rec
        with mock.patch.object(rec, "_HASH_CACHE", hash_cache), \
             mock.patch("brain.reconcile.GLOBAL_RAW", raw_dir):
            rec._needs_index_rebuild()  # prime cache
            (raw_dir / "new.md").write_text("new content")
            assert rec._needs_index_rebuild() is True


class TestProbeIfNeeded:
    def test_no_profile_launches_probe(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        import brain.reconcile as rec
        with mock.patch("brain.reconcile.GLOBAL_RAW", raw), \
             mock.patch("subprocess.Popen") as mock_popen:
            result = rec._probe_if_needed("new-host", str(tmp_path))
        assert result is True
        mock_popen.assert_called_once()

    def test_fresh_profile_skips_probe(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        profile = raw / "machine_my-host.md"
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        meta = {"name": "m", "metadata": {"updated": now, "type": "machine"}}
        post = frontmatter.Post("body", **meta)
        profile.write_text(frontmatter.dumps(post))

        import brain.reconcile as rec
        with mock.patch("brain.reconcile.GLOBAL_RAW", raw), \
             mock.patch("subprocess.Popen") as mock_popen:
            result = rec._probe_if_needed("my-host", str(tmp_path))
        assert result is False
        mock_popen.assert_not_called()

    def test_stale_profile_launches_probe(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        profile = raw / "machine_old-host.md"
        old_date = "2020-01-01T00:00:00Z"
        meta = {"name": "m", "metadata": {"updated": old_date, "type": "machine"}}
        post = frontmatter.Post("body", **meta)
        profile.write_text(frontmatter.dumps(post))

        import brain.reconcile as rec
        with mock.patch("brain.reconcile.GLOBAL_RAW", raw), \
             mock.patch("subprocess.Popen") as mock_popen:
            result = rec._probe_if_needed("old-host", str(tmp_path))
        assert result is True
        mock_popen.assert_called_once()
