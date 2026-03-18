"""Tests for HTML template rendering."""
import pytest

from get_cc_chat.session import Session, Message, ToolCall
from get_cc_chat.renderer import render_html, tool_summary


def _session(**kwargs):
    defaults = dict(
        session_id="abc123",
        project="/Users/chris/myproject",
        started_at="2026-03-17T10:00:00.000Z",
        messages=[],
    )
    defaults.update(kwargs)
    return Session(**defaults)


# --- tool_summary helper ---


class TestToolSummary:
    def test_bash(self):
        tc = ToolCall(name="Bash", input={"command": "ls -la"})
        assert "ls -la" in tool_summary(tc)

    def test_read(self):
        tc = ToolCall(name="Read", input={"file_path": "/tmp/foo.py"})
        assert "/tmp/foo.py" in tool_summary(tc)

    def test_edit(self):
        tc = ToolCall(
            name="Edit",
            input={"file_path": "/tmp/bar.py", "old_string": "a", "new_string": "b"},
        )
        assert "/tmp/bar.py" in tool_summary(tc)

    def test_grep(self):
        tc = ToolCall(name="Grep", input={"pattern": "TODO"})
        assert "TODO" in tool_summary(tc)

    def test_glob(self):
        tc = ToolCall(name="Glob", input={"pattern": "**/*.py"})
        assert "**/*.py" in tool_summary(tc)

    def test_unknown_shows_name(self):
        tc = ToolCall(name="WebSearch", input={"query": "test"})
        assert "WebSearch" in tool_summary(tc)

    def test_bash_long_command_truncated(self):
        long_cmd = "x" * 200
        tc = ToolCall(name="Bash", input={"command": long_cmd})
        result = tool_summary(tc)
        assert len(result) < 200


# --- HTML structure ---


class TestHtmlStructure:
    def test_valid_html5(self):
        html = render_html(_session())
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_css_inlined(self):
        html = render_html(_session())
        assert "<style>" in html or "<style " in html

    def test_no_external_stylesheets(self):
        html = render_html(_session())
        assert 'rel="stylesheet"' not in html


# --- Header ---


class TestHeader:
    def test_project_name(self):
        html = render_html(_session(project="/Users/chris/myproject"))
        assert "myproject" in html

    def test_session_date(self):
        html = render_html(_session(started_at="2026-03-17T10:00:00.000Z"))
        assert "2026-03-17" in html

    def test_export_badge(self):
        html = render_html(_session())
        assert "Exported from Claude Code" in html


# --- Messages ---


class TestMessages:
    def test_user_text(self):
        html = render_html(_session(messages=[
            Message(role="user", timestamp="t", text="Hello world"),
        ]))
        assert "Hello world" in html

    def test_assistant_text(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text="Hi there"),
        ]))
        assert "Hi there" in html

    def test_role_classes(self):
        html = render_html(_session(messages=[
            Message(role="user", timestamp="t1", text="Q"),
            Message(role="assistant", timestamp="t2", text="A"),
        ]))
        assert "message--user" in html
        assert "message--assistant" in html

    def test_order_preserved(self):
        html = render_html(_session(messages=[
            Message(role="user", timestamp="t1", text="AAA_FIRST"),
            Message(role="assistant", timestamp="t2", text="BBB_SECOND"),
            Message(role="user", timestamp="t3", text="CCC_THIRD"),
        ]))
        assert html.index("AAA_FIRST") < html.index("BBB_SECOND") < html.index("CCC_THIRD")


# --- Tool calls ---


class TestToolCallRendering:
    def test_details_element(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "ls"}, result="out"),
            ]),
        ]))
        assert "<details" in html
        assert "<summary" in html

    def test_bash_summary_in_output(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "echo hello"}, result="hello"),
            ]),
        ]))
        assert "echo hello" in html

    def test_result_inside_details(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "echo hello"}, result="RESULT_TEXT_XYZ"),
            ]),
        ]))
        details_start = html.index("<details")
        details_end = html.index("</details>")
        assert "RESULT_TEXT_XYZ" in html[details_start:details_end]

    def test_error_indicated(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "bad"}, result="err msg", is_error=True),
            ]),
        ]))
        body = html.split("</style>", 1)[-1]
        assert "error" in body.lower()

    def test_no_result_renders(self):
        """Tool call with no result should not crash."""
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "ls"}),
            ]),
        ]))
        assert "<details" in html


# --- Truncation ---


class TestTruncation:
    def test_large_result_truncated(self):
        large = "\n".join(f"line {i}" for i in range(150))
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "big"}, result=large),
            ]),
        ]))
        body = html.split("</style>", 1)[-1]
        assert "tool-result--truncated" in body

    def test_small_result_not_truncated(self):
        small = "\n".join(f"line {i}" for i in range(5))
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "small"}, result=small),
            ]),
        ]))
        body = html.split("</style>", 1)[-1]
        assert "tool-result--truncated" not in body


# --- XSS ---


class TestXss:
    def test_tool_result_escaped(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", tool_calls=[
                ToolCall(name="Bash", input={"command": "x"}, result="<script>alert('xss')</script>"),
            ]),
        ]))
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_user_text_escaped(self):
        html = render_html(_session(messages=[
            Message(role="user", timestamp="t", text="<img src=x onerror=alert(1)>"),
        ]))
        assert "<img src=" not in html
        assert "&lt;img" in html


# --- Markdown rendering ---


class TestMarkdownRendering:
    def test_assistant_bold(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text="This is **bold** text"),
        ]))
        assert "<strong>bold</strong>" in html

    def test_assistant_inline_code(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text="Use `print()` here"),
        ]))
        assert "<code>print()</code>" in html

    def test_assistant_fenced_code_block(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text="```python\nprint('hello')\n```"),
        ]))
        assert "codehilite" in html
        assert "print" in html

    def test_assistant_table(self):
        table_md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text=table_md),
        ]))
        assert "<table" in html

    def test_assistant_link(self):
        html = render_html(_session(messages=[
            Message(role="assistant", timestamp="t", text="See [docs](https://example.com)"),
        ]))
        assert 'href="https://example.com"' in html

    def test_user_text_not_markdown_rendered(self):
        """User text with markdown syntax should NOT be converted."""
        html = render_html(_session(messages=[
            Message(role="user", timestamp="t", text="This is **not bold**"),
        ]))
        assert "<strong>" not in html
        assert "**not bold**" in html

    def test_pygments_css_included(self):
        """Pygments CSS for syntax highlighting should be inlined."""
        html = render_html(_session())
        assert ".codehilite" in html
