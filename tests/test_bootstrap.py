"""Tests for brain/bootstrap.py — briefing line generation."""

import pathlib
import platform
import unittest.mock as mock

import pytest


class TestProjectName:
    def test_last_path_component(self):
        from brain.bootstrap import _project_name
        assert _project_name("/Users/siyao/gait_device") == "gait_device"
        assert _project_name("/home/user/my-repo") == "my-repo"

    def test_home_dir_returns_home(self):
        from brain.bootstrap import _project_name
        result = _project_name(str(pathlib.Path.home()))
        assert result  # non-empty
        assert result != ""


class TestMachineLabel:
    def test_darwin_returns_mac_prefix(self):
        from brain.bootstrap import _machine_label
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("platform.machine", return_value="arm64"):
            assert _machine_label("any") == "Mac arm64"

    def test_linux_returns_linux_prefix(self):
        from brain.bootstrap import _machine_label
        with mock.patch("platform.system", return_value="Linux"), \
             mock.patch("platform.machine", return_value="x86_64"):
            assert _machine_label("any") == "Linux x86_64"


class TestGetProjectHint:
    def test_returns_first_non_heading_line(self, tmp_path):
        ctx = tmp_path / ".brain" / "context.md"
        ctx.parent.mkdir(parents=True)
        ctx.write_text("# gait_device — last session 2026-06-01\n\nsome hint here\n- bullet")
        from brain.bootstrap import _get_project_hint
        with mock.patch("brain.bootstrap.repo_context", return_value=ctx):
            hint = _get_project_hint(str(tmp_path))
        assert hint == "some hint here"

    def test_missing_context_returns_none(self, tmp_path):
        from brain.bootstrap import _get_project_hint
        result = _get_project_hint(str(tmp_path / "nonexistent"))
        assert result is None

    def test_hint_capped_at_120_chars(self, tmp_path):
        ctx = tmp_path / ".brain" / "context.md"
        ctx.parent.mkdir(parents=True)
        ctx.write_text("x" * 200)
        from brain.bootstrap import _get_project_hint
        with mock.patch("brain.bootstrap.repo_context", return_value=ctx):
            hint = _get_project_hint(str(tmp_path))
        assert len(hint) <= 120


class TestCheckNewRepo:
    def test_missing_brain_dir_is_new(self, tmp_path):
        from brain.bootstrap import _check_new_repo
        assert _check_new_repo(str(tmp_path)) is True

    def test_existing_brain_dir_is_not_new(self, tmp_path):
        (tmp_path / ".brain").mkdir()
        from brain.bootstrap import _check_new_repo
        assert _check_new_repo(str(tmp_path)) is False


class TestMain:
    def test_outputs_brain_prefix(self, tmp_path, capsys):
        from brain.bootstrap import main
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("platform.machine", return_value="arm64"):
            main(["--cwd", str(tmp_path), "--machine", "test-host"])
        out = capsys.readouterr().out
        assert out.startswith("[BRAIN]")

    def test_includes_project_name(self, tmp_path, capsys):
        repo = tmp_path / "gait_device"
        repo.mkdir()
        from brain.bootstrap import main
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("platform.machine", return_value="arm64"):
            main(["--cwd", str(repo), "--machine", "test-host"])
        out = capsys.readouterr().out
        assert "gait_device" in out

    def test_new_repo_hint_in_output(self, tmp_path, capsys):
        repo = tmp_path / "new_project"
        repo.mkdir()
        from brain.bootstrap import main
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("platform.machine", return_value="arm64"):
            main(["--cwd", str(repo), "--machine", "test-host"])
        out = capsys.readouterr().out
        assert "new repo" in out

    def test_context_hint_shown_when_present(self, tmp_path, capsys):
        repo = tmp_path / "my_project"
        repo.mkdir()
        brain_dir = repo / ".brain"
        brain_dir.mkdir()
        (brain_dir / "context.md").write_text("last session opened hardware stage\n")
        from brain.bootstrap import main
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("platform.machine", return_value="arm64"):
            main(["--cwd", str(repo), "--machine", "test-host"])
        out = capsys.readouterr().out
        assert "last session opened hardware stage" in out
