"""Session discovery and JSONL parsing for Claude Code conversations."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolCall:
    name: str
    input: dict
    result: str | None = None
    is_error: bool = False


@dataclass
class Message:
    role: str
    timestamp: str
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    project: str
    started_at: str
    messages: list[Message] = field(default_factory=list)


def encode_project_path(path: str) -> str:
    """Encode a project path to the format Claude Code uses for directory names.

    /Users/chris/foo -> -Users-chris-foo

    Claude Code replaces all non-alphanumeric characters with hyphens.
    """
    return re.sub(r"[^a-zA-Z0-9]", "-", path.rstrip("/"))


def list_sessions(history_path: str) -> list[dict]:
    """Read history.jsonl and return deduplicated sessions, most recent first.

    Each entry has: sessionId, display (first prompt), timestamp, project.
    """
    path = Path(history_path)
    if not path.exists():
        return []

    text = path.read_text().strip()
    if not text:
        return []

    # Collect first prompt per session
    seen = {}
    for line in text.splitlines():
        entry = json.loads(line)
        sid = entry.get("sessionId")
        if sid and sid not in seen:
            seen[sid] = entry

    # Sort by timestamp descending
    return sorted(seen.values(), key=lambda e: e.get("timestamp", 0), reverse=True)


def find_session_jsonl(
    session_id: str, claude_dir: str, project: str | None = None
) -> str | None:
    """Find the JSONL file for a given session ID.

    Searches ~/.claude/projects/*/SESSION_ID.jsonl, supporting prefix match.
    If project is specified, only searches that project's directory.
    """
    projects_dir = Path(claude_dir) / "projects"
    if not projects_dir.exists():
        return None

    if project:
        encoded = encode_project_path(project)
        search_dirs = [projects_dir / encoded]
    else:
        search_dirs = [d for d in projects_dir.iterdir() if d.is_dir()]

    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix == ".jsonl" and f.stem.startswith(session_id):
                return str(f)

    return None


def parse_jsonl(jsonl_path: str, session_id: str, project: str) -> Session:
    """Parse a Claude Code session JSONL file into a Session object.

    Handles the message tree structure, API errors, sidechains,
    tool_use/tool_result matching, and assistant message grouping.
    """
    lines = Path(jsonl_path).read_text().strip().splitlines()

    # Parse all JSONL entries
    entries = []
    for line in lines:
        entry = json.loads(line)
        entries.append(entry)

    # Build the full tree from all entries that have uuid/parentUuid,
    # but mark which ones are renderable (user/assistant, non-error).
    uuid_map: dict[str, dict] = {}
    children_map: dict[str | None, list[dict]] = {}

    for entry in entries:
        uuid = entry.get("uuid")
        if not uuid:
            continue
        parent = entry.get("parentUuid")
        uuid_map[uuid] = entry
        children_map.setdefault(parent, []).append(entry)

    # Walk the tree to build linear conversation path,
    # then filter to only renderable entries
    full_path = _walk_tree(children_map, uuid_map)
    path = [
        e for e in full_path
        if e.get("type") in ("user", "assistant")
        and not e.get("isApiErrorMessage")
    ]

    # Build tool_use_id -> tool_result lookup from all user messages with tool results
    tool_results = _collect_tool_results(entries)

    # Convert path entries to Messages, grouping assistant turns
    messages = _build_messages(path, tool_results)

    started_at = messages[0].timestamp if messages else ""

    return Session(
        session_id=session_id,
        project=project,
        started_at=started_at,
        messages=messages,
    )


def _is_renderable(entry: dict) -> bool:
    """Check if an entry is a renderable user/assistant message."""
    return (
        entry.get("type") in ("user", "assistant")
        and not entry.get("isApiErrorMessage")
    )


def _walk_tree(
    children_map: dict[str | None, list[dict]],
    uuid_map: dict[str, dict],
) -> list[dict]:
    """Build the linear conversation path via backward trace from the latest message.

    Parallel tool calls create branching: assistant tool_use entries are chained
    and each tool_result branches off its parent.  The continuation can go through
    ANY tool_result branch, so a forward walk cannot reliably pick the right one.

    Instead we:
    1. Find the latest non-sidechain renderable leaf (the conversation's end).
    2. Trace parentUuid links back to the root.
    3. Expand each assistant node to include chained parallel tool-call siblings
       that aren't already on the main path.
    """
    if not uuid_map:
        return []

    # Identify which uuids have children
    has_children: set[str] = set()
    for parent_uuid, kids in children_map.items():
        if parent_uuid is not None and kids:
            has_children.add(parent_uuid)

    # Find leaf entries that are renderable (user/assistant) and non-sidechain
    leaves = [
        e for e in uuid_map.values()
        if e["uuid"] not in has_children
        and _is_renderable(e)
        and not e.get("isSidechain")
    ]
    if not leaves:
        return []

    latest_leaf = max(leaves, key=lambda e: e.get("timestamp", ""))

    # Trace back to root
    back_path: list[dict] = []
    path_uuids: set[str] = set()
    current: dict | None = latest_leaf
    while current:
        back_path.append(current)
        path_uuids.add(current["uuid"])
        parent_uuid = current.get("parentUuid")
        current = uuid_map.get(parent_uuid) if parent_uuid else None
    back_path.reverse()

    # Expand: for each assistant entry on the path, include any chained
    # assistant children (parallel tool calls) that aren't already on the path.
    expanded: list[dict] = []
    for entry in back_path:
        expanded.append(entry)
        if entry.get("type") == "assistant":
            _collect_parallel_tool_calls(
                entry["uuid"], children_map, path_uuids, expanded,
            )

    return expanded


def _collect_parallel_tool_calls(
    parent_uuid: str,
    children_map: dict[str | None, list[dict]],
    path_uuids: set[str],
    result: list[dict],
) -> None:
    """Recursively add chained assistant children not already on the main path."""
    for child in children_map.get(parent_uuid, []):
        if (
            child["uuid"] not in path_uuids
            and child.get("type") == "assistant"
            and not child.get("isSidechain")
        ):
            result.append(child)
            path_uuids.add(child["uuid"])
            _collect_parallel_tool_calls(
                child["uuid"], children_map, path_uuids, result,
            )


def _collect_tool_results(entries: list[dict]) -> dict[str, tuple[str, bool]]:
    """Build a mapping from tool_use_id to (result_text, is_error)."""
    results = {}
    for entry in entries:
        if entry.get("type") != "user":
            continue
        content = entry.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                is_error = block.get("is_error", False)
                raw = block.get("content", "")
                if isinstance(raw, list):
                    text = "\n".join(
                        item.get("text", "") for item in raw if isinstance(item, dict)
                    )
                else:
                    text = str(raw)
                results[tool_use_id] = (text, is_error)
    return results


def _build_messages(
    path: list[dict], tool_results: dict[str, tuple[str, bool]]
) -> list[Message]:
    """Convert a linear path of entries into grouped Messages."""
    messages: list[Message] = []

    i = 0
    while i < len(path):
        entry = path[i]
        role = entry.get("type")
        timestamp = entry.get("timestamp", "")

        if role == "user":
            text = _extract_user_text(entry)
            if text:
                messages.append(Message(role="user", timestamp=timestamp, text=text))
            i += 1

        elif role == "assistant":
            # Collect consecutive assistant entries that form one turn.
            # A turn ends when we hit a tool result (which starts a new turn
            # after the result) or a user text message.
            text_parts = []
            tool_calls = []

            while i < len(path) and path[i].get("type") == "assistant":
                aentry = path[i]
                content = aentry.get("message", {}).get("content", [])
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tc = _make_tool_call(block, tool_results)
                        tool_calls.append(tc)
                i += 1

                # If the next entry is a user message with tool results only,
                # this turn is complete. Skip the tool result and break so the
                # next assistant response becomes a new message.
                if i < len(path) and path[i].get("type") == "user":
                    if _is_tool_result_only(path[i]):
                        i += 1  # skip tool result user message
                    break

            text = "\n\n".join(text_parts) if text_parts else None
            messages.append(
                Message(
                    role="assistant",
                    timestamp=timestamp,
                    text=text,
                    tool_calls=tool_calls,
                )
            )
        else:
            i += 1

    return messages


def _extract_user_text(entry: dict) -> str | None:
    """Extract display text from a user message entry."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block["text"])
        return "\n".join(texts) if texts else None
    return None


def _is_tool_result_only(entry: dict) -> bool:
    """Check if a user message contains only tool results (no user text)."""
    content = entry.get("message", {}).get("content")
    if not isinstance(content, list):
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result"
        for b in content
    )


def _make_tool_call(
    block: dict, tool_results: dict[str, tuple[str, bool]]
) -> ToolCall:
    """Create a ToolCall from a tool_use content block."""
    tool_use_id = block.get("id", "")
    result_text, is_error = tool_results.get(tool_use_id, (None, False))
    return ToolCall(
        name=block.get("name", ""),
        input=block.get("input", {}),
        result=result_text,
        is_error=is_error,
    )
