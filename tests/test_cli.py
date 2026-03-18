"""Tests for CLI wiring."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from get_cc_chat.cli import main


@pytest.fixture
def fake_claude_home(tmp_path):
    """Create a minimal ~/.claude with one session containing a tool call."""
    claude_dir = tmp_path / ".claude"
    projects_dir = claude_dir / "projects" / "-tmp-proj"
    projects_dir.mkdir(parents=True)

    (claude_dir / "history.jsonl").write_text(
        json.dumps({
            "sessionId": "abc12345-def6-7890-abcd-ef1234567890",
            "display": "List files",
            "timestamp": 1710000000,
            "project": "/tmp/proj",
        }) + "\n"
    )

    lines = [
        json.dumps({
            "parentUuid": None, "isSidechain": False, "type": "user",
            "message": {"role": "user", "content": "List files"},
            "uuid": "u1", "timestamp": "2026-03-17T10:00:00.000Z",
            "sessionId": "abc12345-def6-7890-abcd-ef1234567890",
        }),
        json.dumps({
            "parentUuid": "u1", "isSidechain": False, "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "tool1", "name": "Bash", "input": {"command": "ls"}},
                ],
                "model": "claude-opus-4-6", "id": "msg_a1", "type": "message",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
            "uuid": "a1", "timestamp": "2026-03-17T10:00:01.000Z",
            "sessionId": "abc12345-def6-7890-abcd-ef1234567890",
        }),
        json.dumps({
            "parentUuid": "a1", "isSidechain": False, "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tool1", "content": "file.txt"}],
            },
            "uuid": "tr1", "timestamp": "2026-03-17T10:00:02.000Z",
            "sessionId": "abc12345-def6-7890-abcd-ef1234567890",
        }),
        json.dumps({
            "parentUuid": "tr1", "isSidechain": False, "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here are the files."}],
                "model": "claude-opus-4-6", "id": "msg_a2", "type": "message",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
            "uuid": "a2", "timestamp": "2026-03-17T10:00:03.000Z",
            "sessionId": "abc12345-def6-7890-abcd-ef1234567890",
        }),
    ]
    (projects_dir / "abc12345-def6-7890-abcd-ef1234567890.jsonl").write_text(
        "\n".join(lines) + "\n"
    )

    return tmp_path


# --- --list mode ---


class TestListMode:
    def test_prints_session_info(self, fake_claude_home, capsys):
        with patch.object(Path, "home", return_value=fake_claude_home):
            main(["--list"])
        out = capsys.readouterr().out
        assert "abc12345" in out
        assert "List files" in out

    def test_empty_history(self, tmp_path, capsys):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "history.jsonl").write_text("")
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                main(["--list"])
        err = capsys.readouterr().err
        assert "no sessions" in err.lower()


# --- render mode ---


class TestRenderMode:
    def test_renders_most_recent(self, fake_claude_home, capsys):
        out_file = fake_claude_home / "output.html"
        with patch.object(Path, "home", return_value=fake_claude_home):
            main(["--output", str(out_file)])
        html = out_file.read_text()
        assert "<!DOCTYPE html>" in html
        assert "List files" in html
        assert "Here are the files" in html

    def test_default_output_path(self, fake_claude_home, capsys, monkeypatch):
        monkeypatch.chdir(fake_claude_home)
        with patch.object(Path, "home", return_value=fake_claude_home):
            main([])
        out = capsys.readouterr().out
        assert "chat-abc12345.html" in out
        assert (fake_claude_home / "chat-abc12345.html").exists()

    def test_specific_session_id(self, fake_claude_home, capsys):
        out_file = fake_claude_home / "out.html"
        with patch.object(Path, "home", return_value=fake_claude_home):
            main(["abc12345", "--output", str(out_file)])
        assert out_file.exists()
        html = out_file.read_text()
        assert "List files" in html

    def test_session_not_found(self, fake_claude_home, capsys):
        with patch.object(Path, "home", return_value=fake_claude_home):
            with pytest.raises(SystemExit):
                main(["nonexistent-id"])
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_no_history(self, tmp_path, capsys):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "history.jsonl").write_text("")
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                main([])
        err = capsys.readouterr().err
        assert "no sessions" in err.lower()


# --- --no-tools ---


class TestNoToolsMode:
    def test_strips_tool_calls(self, fake_claude_home, capsys):
        out_file = fake_claude_home / "out.html"
        with patch.object(Path, "home", return_value=fake_claude_home):
            main(["--no-tools", "--output", str(out_file)])
        html = out_file.read_text()
        assert "<details" not in html
        assert "Let me check" in html
        assert "Here are the files" in html


# --- --project filter ---


class TestProjectFilter:
    def test_list_with_project(self, fake_claude_home, capsys):
        with patch.object(Path, "home", return_value=fake_claude_home):
            main(["--list", "--project", "/tmp/proj"])
        out = capsys.readouterr().out
        assert "abc12345" in out

    def test_list_filters_other_project(self, fake_claude_home, capsys):
        with patch.object(Path, "home", return_value=fake_claude_home):
            with pytest.raises(SystemExit):
                main(["--list", "--project", "/tmp/other"])
        err = capsys.readouterr().err
        assert "no sessions" in err.lower()
