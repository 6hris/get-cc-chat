"""Tests for session discovery and JSONL parsing."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from get_cc_chat.session import (
    ToolCall,
    Message,
    Session,
    parse_jsonl,
    list_sessions,
    find_session_jsonl,
    encode_project_path,
)


# --- Helpers to build fake JSONL lines ---

def make_user_msg(uuid, parent_uuid, text, timestamp="2026-03-17T10:00:00.000Z", sidechain=False):
    return json.dumps({
        "parentUuid": parent_uuid,
        "isSidechain": sidechain,
        "type": "user",
        "message": {"role": "user", "content": text},
        "uuid": uuid,
        "timestamp": timestamp,
        "sessionId": "test-session",
        "cwd": "/tmp/test",
    })


def make_assistant_text(uuid, parent_uuid, text, timestamp="2026-03-17T10:00:01.000Z", sidechain=False):
    return json.dumps({
        "parentUuid": parent_uuid,
        "isSidechain": sidechain,
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": "claude-opus-4-6",
            "id": f"msg_{uuid}",
            "type": "message",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        "uuid": uuid,
        "timestamp": timestamp,
        "sessionId": "test-session",
        "cwd": "/tmp/test",
    })


def make_assistant_tool_use(uuid, parent_uuid, tool_name, tool_input, tool_use_id, timestamp="2026-03-17T10:00:02.000Z", sidechain=False):
    return json.dumps({
        "parentUuid": parent_uuid,
        "isSidechain": sidechain,
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_input}],
            "model": "claude-opus-4-6",
            "id": f"msg_{uuid}",
            "type": "message",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        "uuid": uuid,
        "timestamp": timestamp,
        "sessionId": "test-session",
        "cwd": "/tmp/test",
    })


def make_tool_result(uuid, parent_uuid, tool_use_id, result_text, timestamp="2026-03-17T10:00:03.000Z", is_error=False):
    return json.dumps({
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": result_text, "is_error": is_error},
            ],
        },
        "uuid": uuid,
        "timestamp": timestamp,
        "sessionId": "test-session",
        "cwd": "/tmp/test",
    })


def make_error_msg(uuid, parent_uuid, timestamp="2026-03-17T10:00:01.000Z"):
    return json.dumps({
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "type": "assistant",
        "isApiErrorMessage": True,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "API Error: 500"}],
            "model": "claude-opus-4-6",
            "id": f"msg_{uuid}",
            "type": "message",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
        "uuid": uuid,
        "timestamp": timestamp,
        "sessionId": "test-session",
        "cwd": "/tmp/test",
    })


def make_progress_msg(uuid, parent_uuid):
    return json.dumps({
        "parentUuid": parent_uuid,
        "type": "progress",
        "uuid": uuid,
        "timestamp": "2026-03-17T10:00:01.500Z",
        "sessionId": "test-session",
    })


def write_jsonl(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


# --- encode_project_path ---

class TestEncodeProjectPath:
    def test_basic(self):
        assert encode_project_path("/Users/chris/foo") == "-Users-chris-foo"

    def test_trailing_slash(self):
        assert encode_project_path("/Users/chris/foo/") == "-Users-chris-foo"

    def test_underscores_become_hyphens(self):
        assert encode_project_path("/Users/chris/get_terminal_chat") == "-Users-chris-get-terminal-chat"

    def test_dots_become_hyphens(self):
        assert encode_project_path("/Users/chris/my.project") == "-Users-chris-my-project"


# --- parse_jsonl: simple conversation ---

class TestParseJsonlSimple:
    def test_single_exchange(self, tmp_path):
        """User asks a question, assistant responds with text."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_assistant_text("a1", "u1", "Hi there!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[0].text == "Hello"
        assert session.messages[1].role == "assistant"
        assert session.messages[1].text == "Hi there!"

    def test_multi_turn(self, tmp_path):
        """Multiple user/assistant exchanges."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "First question"),
            make_assistant_text("a1", "u1", "First answer"),
            make_user_msg("u2", "a1", "Second question"),
            make_assistant_text("a2", "u2", "Second answer"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 4
        assert session.messages[2].text == "Second question"
        assert session.messages[3].text == "Second answer"


# --- parse_jsonl: tool calls ---

class TestParseJsonlToolCalls:
    def test_tool_use_with_result(self, tmp_path):
        """Assistant makes a tool call, gets a result."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "List files"),
            make_assistant_tool_use("a1", "u1", "Bash", {"command": "ls"}, "tool1"),
            make_tool_result("tr1", "a1", "tool1", "file1.txt\nfile2.txt"),
            make_assistant_text("a2", "tr1", "Here are the files."),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        # Should have: user msg, assistant msg with tool call, assistant text
        # The tool result gets attached to the tool call, not as a separate message
        assert session.messages[0].role == "user"
        assert session.messages[0].text == "List files"

        # Assistant message with tool call
        assert session.messages[1].role == "assistant"
        assert len(session.messages[1].tool_calls) == 1
        tc = session.messages[1].tool_calls[0]
        assert tc.name == "Bash"
        assert tc.input == {"command": "ls"}
        assert tc.result == "file1.txt\nfile2.txt"
        assert tc.is_error is False

        # Follow-up assistant text
        assert session.messages[2].role == "assistant"
        assert session.messages[2].text == "Here are the files."

    def test_tool_error(self, tmp_path):
        """Tool result marked as error."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Read file"),
            make_assistant_tool_use("a1", "u1", "Read", {"file_path": "/bad"}, "tool1"),
            make_tool_result("tr1", "a1", "tool1", "File not found", is_error=True),
            make_assistant_text("a2", "tr1", "Sorry, file not found."),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        tc = session.messages[1].tool_calls[0]
        assert tc.is_error is True
        assert tc.result == "File not found"


# --- parse_jsonl: error messages and filtering ---

class TestParseJsonlFiltering:
    def test_skips_api_errors(self, tmp_path):
        """API error messages should be skipped."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_error_msg("e1", "u1"),
            make_assistant_text("a1", "u1", "Hi there!", sidechain=False),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 2
        assert session.messages[1].text == "Hi there!"

    def test_skips_progress_messages(self, tmp_path):
        """Progress messages should be skipped."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_progress_msg("p1", "u1"),
            make_assistant_text("a1", "u1", "Hi there!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 2


# --- parse_jsonl: branching / retries ---

class TestParseJsonlBranching:
    def test_picks_non_sidechain_over_sidechain(self, tmp_path):
        """When there are sidechain branches, follow the non-sidechain path."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_assistant_text("a1_side", "u1", "Sidechain response", sidechain=True),
            make_assistant_text("a1_main", "u1", "Main response", sidechain=False),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 2
        assert session.messages[1].text == "Main response"

    def test_retry_after_error(self, tmp_path):
        """Error followed by retry - should skip error, follow retry."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_error_msg("e1", "u1"),
            make_assistant_text("a1", "u1", "Good response"),
            make_user_msg("u2", "a1", "Follow up"),
            make_assistant_text("a2", "u2", "Follow up answer"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 4
        assert session.messages[0].text == "Hello"
        assert session.messages[1].text == "Good response"
        assert session.messages[2].text == "Follow up"
        assert session.messages[3].text == "Follow up answer"


# --- parse_jsonl: assistant message grouping ---

class TestParseJsonlGrouping:
    def test_groups_consecutive_assistant_parts(self, tmp_path):
        """Multiple assistant JSONL lines for one turn (text + tool_use) get grouped."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Do something"),
            make_assistant_text("a1", "u1", "Let me check.", timestamp="2026-03-17T10:00:01.000Z"),
            make_assistant_tool_use("a2", "a1", "Bash", {"command": "ls"}, "tool1", timestamp="2026-03-17T10:00:02.000Z"),
            make_tool_result("tr1", "a2", "tool1", "output"),
            make_assistant_text("a3", "tr1", "Done!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        # Should be: user, assistant(text + tool), assistant(text)
        assert session.messages[0].role == "user"
        assert session.messages[1].role == "assistant"
        assert session.messages[1].text == "Let me check."
        assert len(session.messages[1].tool_calls) == 1
        assert session.messages[2].role == "assistant"
        assert session.messages[2].text == "Done!"


# --- list_sessions ---

class TestListSessions:
    def test_lists_from_history(self, tmp_path):
        """Reads history.jsonl and returns deduplicated sessions."""
        history = tmp_path / "history.jsonl"
        history.write_text(
            json.dumps({"display": "first prompt", "timestamp": 1000, "project": "/tmp/a", "sessionId": "s1"}) + "\n"
            + json.dumps({"display": "second msg", "timestamp": 2000, "project": "/tmp/a", "sessionId": "s1"}) + "\n"
            + json.dumps({"display": "other session", "timestamp": 3000, "project": "/tmp/b", "sessionId": "s2"}) + "\n"
        )
        sessions = list_sessions(str(history))
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0]["sessionId"] == "s2"
        assert sessions[0]["display"] == "other session"
        assert sessions[1]["sessionId"] == "s1"
        assert sessions[1]["display"] == "first prompt"

    def test_empty_history(self, tmp_path):
        history = tmp_path / "history.jsonl"
        history.write_text("")
        sessions = list_sessions(str(history))
        assert sessions == []


# --- find_session_jsonl ---

class TestFindSessionJsonl:
    def test_finds_by_session_id(self, tmp_path):
        """Finds session JSONL file given a session ID and claude dir."""
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-tmp-myproject"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "abc123.jsonl"
        jsonl_file.write_text("")

        result = find_session_jsonl("abc123", str(claude_dir))
        assert result == str(jsonl_file)

    def test_prefix_match(self, tmp_path):
        """Matches session ID by prefix."""
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-tmp-proj"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "abc123-def456-ghi789.jsonl"
        jsonl_file.write_text("")

        result = find_session_jsonl("abc123", str(claude_dir))
        assert result == str(jsonl_file)

    def test_not_found(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        result = find_session_jsonl("nonexistent", str(claude_dir))
        assert result is None

    def test_filters_by_project(self, tmp_path):
        """When project is specified, only searches that project dir."""
        claude_dir = tmp_path / ".claude"
        proj_a = claude_dir / "projects" / "-tmp-a"
        proj_b = claude_dir / "projects" / "-tmp-b"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)
        (proj_a / "sess1.jsonl").write_text("")
        (proj_b / "sess2.jsonl").write_text("")

        result = find_session_jsonl("sess1", str(claude_dir), project="/tmp/a")
        assert result is not None
        result = find_session_jsonl("sess2", str(claude_dir), project="/tmp/a")
        assert result is None

    def test_project_with_special_chars(self, tmp_path):
        """Project path with underscores/dots should still find the right dir."""
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-tmp-my-project"
        proj_dir.mkdir(parents=True)
        (proj_dir / "sess1.jsonl").write_text("")

        result = find_session_jsonl("sess1", str(claude_dir), project="/tmp/my_project")
        assert result is not None


# --- parse_jsonl: parallel tool calls ---

class TestParseJsonlParallelToolCalls:
    def test_chained_tool_calls_not_lost(self, tmp_path):
        """Parallel tool calls create chained assistant entries; walker must follow the chain."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Do two things"),
            # Assistant makes two tool calls as CHAINED entries (parallel execution)
            make_assistant_tool_use("a1", "u1", "Bash", {"command": "ls"}, "t1",
                                   timestamp="2026-03-17T10:00:01.000Z"),
            make_assistant_tool_use("a2", "a1", "Bash", {"command": "pwd"}, "t2",
                                   timestamp="2026-03-17T10:00:01.100Z"),
            # Tool results branch off from their respective tool_use parents
            make_tool_result("tr1", "a1", "t1", "file.txt",
                            timestamp="2026-03-17T10:00:02.000Z"),
            make_tool_result("tr2", "a2", "t2", "/tmp",
                            timestamp="2026-03-17T10:00:02.100Z"),
            # Conversation continues after the last tool result
            make_assistant_text("a3", "tr2", "All done!",
                               timestamp="2026-03-17T10:00:03.000Z"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        texts = [m.text for m in session.messages if m.text]
        assert "All done!" in texts
        all_tools = [tc for m in session.messages for tc in m.tool_calls]
        assert len(all_tools) == 2

    def test_continuation_through_non_last_result(self, tmp_path):
        """Continuation can go through ANY tool result, not necessarily the last in the chain."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Do two things"),
            make_assistant_tool_use("a1", "u1", "Bash", {"command": "ls"}, "t1",
                                   timestamp="2026-03-17T10:00:01.000Z"),
            make_assistant_tool_use("a2", "a1", "Bash", {"command": "pwd"}, "t2",
                                   timestamp="2026-03-17T10:00:01.100Z"),
            # tr2 comes back first (dead end), tr1 has the continuation
            make_tool_result("tr2", "a2", "t2", "/tmp",
                            timestamp="2026-03-17T10:00:02.000Z"),
            make_tool_result("tr1", "a1", "t1", "file.txt",
                            timestamp="2026-03-17T10:00:02.100Z"),
            make_assistant_text("a3", "tr1", "All done!",
                               timestamp="2026-03-17T10:00:03.000Z"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        texts = [m.text for m in session.messages if m.text]
        assert "All done!" in texts
        all_tools = [tc for m in session.messages for tc in m.tool_calls]
        assert len(all_tools) == 2

    def test_three_parallel_tool_calls(self, tmp_path):
        """Three chained parallel tool calls should all be traversed."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Do three things"),
            make_assistant_tool_use("a1", "u1", "Bash", {"command": "ls"}, "t1",
                                   timestamp="2026-03-17T10:00:01.000Z"),
            make_assistant_tool_use("a2", "a1", "Bash", {"command": "pwd"}, "t2",
                                   timestamp="2026-03-17T10:00:01.100Z"),
            make_assistant_tool_use("a3", "a2", "Bash", {"command": "whoami"}, "t3",
                                   timestamp="2026-03-17T10:00:01.200Z"),
            make_tool_result("tr1", "a1", "t1", "file.txt",
                            timestamp="2026-03-17T10:00:02.000Z"),
            make_tool_result("tr2", "a2", "t2", "/tmp",
                            timestamp="2026-03-17T10:00:02.100Z"),
            make_tool_result("tr3", "a3", "t3", "chris",
                            timestamp="2026-03-17T10:00:02.200Z"),
            make_assistant_text("a4", "tr3", "All done!",
                               timestamp="2026-03-17T10:00:03.000Z"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        texts = [m.text for m in session.messages if m.text]
        assert "All done!" in texts
        all_tools = [tc for m in session.messages for tc in m.tool_calls]
        assert len(all_tools) == 3


# --- parse_jsonl: edge cases ---

class TestParseJsonlEdgeCases:
    def test_multiple_tool_calls_in_one_assistant_msg(self, tmp_path):
        """Assistant issues multiple tool calls in a single content block."""
        jsonl_path = tmp_path / "session.jsonl"
        # Single assistant entry with two tool_use blocks
        assistant_entry = json.dumps({
            "parentUuid": "u1",
            "isSidechain": False,
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                    {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pwd"}},
                ],
                "model": "claude-opus-4-6",
                "id": "msg_multi",
                "type": "message",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
            "uuid": "a1",
            "timestamp": "2026-03-17T10:00:01.000Z",
            "sessionId": "test-session",
            "cwd": "/tmp/test",
        })
        # Tool results for both
        tool_results_entry = json.dumps({
            "parentUuid": "a1",
            "isSidechain": False,
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "file.txt"},
                    {"type": "tool_result", "tool_use_id": "t2", "content": "/tmp/test"},
                ],
            },
            "uuid": "tr1",
            "timestamp": "2026-03-17T10:00:02.000Z",
            "sessionId": "test-session",
            "cwd": "/tmp/test",
        })
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Check dir"),
            assistant_entry,
            tool_results_entry,
            make_assistant_text("a2", "tr1", "Here you go."),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages[1].tool_calls) == 2
        assert session.messages[1].tool_calls[0].result == "file.txt"
        assert session.messages[1].tool_calls[1].result == "/tmp/test"

    def test_user_interrupt(self, tmp_path):
        """User interrupts - message with [Request interrupted by user]."""
        jsonl_path = tmp_path / "session.jsonl"
        interrupt_msg = json.dumps({
            "parentUuid": "a1",
            "isSidechain": False,
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "[Request interrupted by user]"}],
            },
            "uuid": "int1",
            "timestamp": "2026-03-17T10:00:02.000Z",
            "sessionId": "test-session",
            "cwd": "/tmp/test",
        })
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_assistant_text("a1", "u1", "Let me think..."),
            interrupt_msg,
            make_user_msg("u2", "int1", "Never mind, do this instead"),
            make_assistant_text("a2", "u2", "Sure!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 5
        assert session.messages[2].text == "[Request interrupted by user]"
        assert session.messages[3].text == "Never mind, do this instead"

    def test_session_metadata(self, tmp_path):
        """Session object has correct metadata."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello", timestamp="2026-03-17T09:00:00.000Z"),
            make_assistant_text("a1", "u1", "Hi!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="my-session", project="/Users/chris/proj")
        assert session.session_id == "my-session"
        assert session.project == "/Users/chris/proj"
        assert session.started_at == "2026-03-17T09:00:00.000Z"

    def test_empty_session(self, tmp_path):
        """Empty JSONL file produces empty session."""
        jsonl_path = tmp_path / "session.jsonl"
        jsonl_path.write_text("")
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert session.messages == []

    def test_system_message_bridge(self, tmp_path):
        """System messages between error and retry should be traversed as bridges."""
        jsonl_path = tmp_path / "session.jsonl"
        system_msg = json.dumps({
            "parentUuid": "e1",
            "isSidechain": False,
            "type": "system",
            "message": {"role": "system", "content": ""},
            "uuid": "sys1",
            "timestamp": "2026-03-17T10:00:01.500Z",
            "sessionId": "test-session",
        })
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "Hello"),
            make_error_msg("e1", "u1"),
            system_msg,
            make_user_msg("u2", "sys1", "Hello again"),
            make_assistant_text("a1", "u2", "Hi!"),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        # Should traverse through error+system to find the retry
        assert len(session.messages) == 3
        assert session.messages[0].text == "Hello"
        assert session.messages[1].text == "Hello again"
        assert session.messages[2].text == "Hi!"

    def test_real_world_text_and_tool_mix(self, tmp_path):
        """Simulates a realistic flow: user asks, assistant explains + runs tool + explains."""
        jsonl_path = tmp_path / "session.jsonl"
        write_jsonl(jsonl_path, [
            make_user_msg("u1", None, "What files are here?"),
            make_assistant_text("a1", "u1", "Let me check."),
            make_assistant_tool_use("a2", "a1", "Bash", {"command": "ls -la"}, "t1"),
            make_tool_result("tr1", "a2", "t1", "total 8\ndrwxr-xr-x  3 chris  staff  96 Mar 17 10:00 .\n-rw-r--r--  1 chris  staff  42 Mar 17 10:00 hello.py"),
            make_assistant_text("a3", "tr1", "You have a `hello.py` file."),
            make_user_msg("u2", "a3", "Show me the contents"),
            make_assistant_tool_use("a4", "u2", "Read", {"file_path": "/tmp/hello.py"}, "t2"),
            make_tool_result("tr2", "a4", "t2", "print('hello world')"),
            make_assistant_text("a5", "tr2", "It prints hello world."),
        ])
        session = parse_jsonl(str(jsonl_path), session_id="test", project="/tmp/test")
        assert len(session.messages) == 6
        assert session.messages[0].text == "What files are here?"
        assert session.messages[1].text == "Let me check."
        assert session.messages[1].tool_calls[0].name == "Bash"
        assert session.messages[2].text == "You have a `hello.py` file."
        assert session.messages[3].text == "Show me the contents"
        assert session.messages[4].tool_calls[0].name == "Read"
        assert session.messages[5].text == "It prints hello world."
