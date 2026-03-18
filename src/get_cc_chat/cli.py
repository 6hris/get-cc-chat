"""CLI entry point for get-cc-chat."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from .renderer import render_html
from .session import find_session_jsonl, list_sessions, parse_jsonl


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="get-cc-chat",
        description="Export Claude Code sessions as shareable HTML pages",
    )
    parser.add_argument(
        "session_id", nargs="?", default=None,
        help="Session UUID or prefix (default: most recent)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List recent sessions with timestamps and first prompt",
    )
    parser.add_argument(
        "--project", default=None,
        help="Filter to sessions from a specific project directory",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output HTML path (default: ./chat-<short-id>.html)",
    )
    parser.add_argument(
        "--no-tools", action="store_true",
        help="Omit tool call/result details, show only conversation text",
    )
    parser.add_argument(
        "--gist", action="store_true",
        help="Upload to GitHub Gist, print shareable URL",
    )

    args = parser.parse_args(argv)
    claude_dir = Path.home() / ".claude"
    history_path = str(claude_dir / "history.jsonl")

    if args.list:
        _handle_list(history_path, args.project)
        return

    # Determine which session to render
    if args.session_id:
        session_id = args.session_id
        jsonl_path = find_session_jsonl(session_id, str(claude_dir), project=args.project)
        if not jsonl_path:
            print(f"Session not found: {session_id}", file=sys.stderr)
            sys.exit(1)
        project = args.project or _lookup_project(history_path, session_id)
    else:
        sessions = list_sessions(history_path)
        if args.project:
            sessions = [s for s in sessions if s.get("project") == args.project]
        if not sessions:
            print("No sessions found.", file=sys.stderr)
            sys.exit(1)
        recent = sessions[0]
        session_id = recent["sessionId"]
        project = recent.get("project", "")
        jsonl_path = find_session_jsonl(session_id, str(claude_dir), project=project)
        if not jsonl_path:
            print(f"Session file not found for: {session_id}", file=sys.stderr)
            sys.exit(1)

    session = parse_jsonl(jsonl_path, session_id, project)

    if args.no_tools:
        for msg in session.messages:
            msg.tool_calls = []

    html = render_html(session)

    output_path = args.output or f"chat-{session_id[:8]}.html"
    Path(output_path).write_text(html)
    print(f"Wrote {output_path}")


def _handle_list(history_path, project=None):
    """Print recent sessions."""
    sessions = list_sessions(history_path)
    if project:
        sessions = [s for s in sessions if s.get("project") == project]
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        sys.exit(1)

    for entry in sessions[:20]:
        sid = entry.get("sessionId", "")[:8]
        ts = entry.get("timestamp", 0)
        if ts > 1e12:
            ts = ts / 1000
        try:
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            date = "unknown"
        display = entry.get("display", "")[:60]
        proj = entry.get("project", "")
        print(f"  {sid}  {date}  {display}  ({proj})")


def _lookup_project(history_path, session_id):
    """Look up a session's project from history.jsonl."""
    for s in list_sessions(history_path):
        if s.get("sessionId", "").startswith(session_id):
            return s.get("project", "")
    return ""
