"""Tests for GitHub Gist integration."""
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from get_cc_chat.gist import check_gh_cli, create_gist


class TestCheckGhCli:
    def test_returns_true_when_installed(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert check_gh_cli() is True

    def test_returns_false_when_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_gh_cli() is False


class TestCreateGist:
    def test_returns_gist_url(self, tmp_path):
        html_file = tmp_path / "chat.html"
        html_file.write_text("<html>test</html>")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://gist.github.com/abc123def456\n",
            )
            url = create_gist(str(html_file))

        assert url == "https://gisthost.github.io/?abc123def456"
        # Verify gh was called correctly
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "gist" in cmd
        assert "create" in cmd
        assert "--public" in cmd

    def test_raises_on_failure(self, tmp_path):
        html_file = tmp_path / "chat.html"
        html_file.write_text("<html>test</html>")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="auth required",
            )
            with pytest.raises(RuntimeError, match="auth required"):
                create_gist(str(html_file))

    def test_parses_gist_id_from_url(self, tmp_path):
        html_file = tmp_path / "chat.html"
        html_file.write_text("<html>test</html>")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://gist.github.com/user/a1b2c3d4e5f6\n",
            )
            url = create_gist(str(html_file))

        assert url == "https://gisthost.github.io/?a1b2c3d4e5f6"
