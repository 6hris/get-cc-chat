"""HTML rendering for Claude Code sessions."""
from pathlib import Path

import markdown as md_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pygments.formatters import HtmlFormatter

from .session import Session, ToolCall

TOOL_SUMMARY_TRUNCATE = 80
RESULT_LINE_THRESHOLD = 100


def tool_summary(tc: ToolCall) -> str:
    """Generate a one-line summary for a tool call."""
    if tc.name == "Bash":
        cmd = tc.input.get("command", "")
        if len(cmd) > TOOL_SUMMARY_TRUNCATE:
            cmd = cmd[:TOOL_SUMMARY_TRUNCATE] + "\u2026"
        return f"Bash: {cmd}"
    elif tc.name == "Read":
        return f"Read: {tc.input.get('file_path', '')}"
    elif tc.name == "Edit":
        return f"Edit: {tc.input.get('file_path', '')}"
    elif tc.name in ("Grep", "Glob"):
        return f"{tc.name}: {tc.input.get('pattern', '')}"
    else:
        return tc.name


def _line_count(text):
    """Count newlines in text (Jinja2 filter)."""
    if not text:
        return 0
    return text.count("\n")


def _basename(path):
    """Extract last path component (Jinja2 filter)."""
    if not path:
        return ""
    return path.rstrip("/").split("/")[-1]


_MD_EXTENSIONS = ["fenced_code", "codehilite", "tables"]
_MD_EXT_CONFIG = {
    "codehilite": {"css_class": "codehilite", "guess_lang": False},
}


def _markdown_filter(text):
    """Convert markdown text to HTML (Jinja2 filter). Returns Markup (safe)."""
    if not text:
        return ""
    html = md_lib.markdown(text, extensions=_MD_EXTENSIONS, extension_configs=_MD_EXT_CONFIG)
    return Markup(html)


def render_html(session: Session) -> str:
    """Render a Session to a self-contained HTML string."""
    template_dir = Path(__file__).parent
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(),
    )
    env.globals["tool_summary"] = tool_summary
    env.globals["RESULT_LINE_THRESHOLD"] = RESULT_LINE_THRESHOLD
    env.filters["line_count"] = _line_count
    env.filters["basename"] = _basename
    env.filters["md"] = _markdown_filter

    pygments_css = HtmlFormatter(style="monokai").get_style_defs(".codehilite")

    template = env.get_template("template.html")
    return template.render(session=session, pygments_css=Markup(pygments_css))
