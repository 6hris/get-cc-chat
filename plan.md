# get-cc-chat: Implementation Plan

## Context

We want a CLI tool that exports Claude Code terminal sessions as shareable HTML pages — similar to ChatGPT's "share chat" feature but for terminal-based AI coding sessions. The tool is scoped to Claude Code only, must cost $0, and serves as a personal tool.

Claude Code stores full conversation data as JSONL files in `~/.claude/projects/{encoded-path}/{sessionId}/subagents/agent-*.jsonl`. The global session index lives at `~/.claude/history.jsonl`.

## Architecture

**Python CLI tool** installed via `pip install -e .`, providing the `get-cc-chat` command.

Two output modes:
1. **Standalone HTML file** (default) — self-contained, shareable however the user wants
2. **GitHub Gist** (`--gist` flag) — uploads HTML to a public Gist, returns a `gisthost.github.io` URL for instant browser viewing. Requires `gh` CLI.

## Project Structure

```
get_cc_chat/
├── pyproject.toml
├── idea.txt
└── src/
    └── get_cc_chat/
        ├── __init__.py
        ├── cli.py          # argparse CLI entry point
        ├── session.py      # Session discovery + JSONL parsing
        ├── renderer.py     # Conversation → HTML via Jinja2 + markdown
        ├── template.html   # Self-contained HTML/CSS template
        └── gist.py         # GitHub Gist upload via `gh` CLI
```

## CLI Interface

```
get-cc-chat [SESSION_ID] [OPTIONS]

Positional:
  SESSION_ID              Session UUID or prefix (optional; defaults to most recent)

Options:
  --list                  List recent sessions with timestamps and first prompt
  --project PATH          Filter to sessions from a specific project directory
  --output FILE           Output HTML path (default: ./chat-<short-id>.html)
  --gist                  Upload to GitHub Gist, print shareable gisthost URL
  --no-tools              Omit tool call/result details, show only conversation text
```

## Implementation Steps

### Step 1: Project scaffolding
- Create `pyproject.toml` with dependencies (`markdown`, `pygments`, `jinja2`) and `[project.scripts]` entry point
- Create `src/get_cc_chat/__init__.py`
- Verify installable with `pip install -e .`

### Step 2: Session discovery and JSONL parsing (`session.py`)

**Session discovery:**
- `--list`: Read `~/.claude/history.jsonl`, deduplicate by sessionId, show 20 most recent with timestamp + first prompt + project
- Default (no ID): Take most recent from history.jsonl
- With ID: Match against known session IDs (prefix match OK)
- From the `project` field in history.jsonl, derive the encoded path (`/Users/chris/foo` → `-Users-chris-foo`) to locate JSONL files under `~/.claude/projects/`

**Identify the main conversation JSONL:**
- Within `~/.claude/projects/{encoded-path}/{sessionId}/`, find the agent JSONL that represents the main conversation (not a subagent). Use `.meta.json` files to distinguish — subagents have `agentType` like "Explore" or "Plan", while the main conversation agent may lack this or have a different type.

**JSONL parsing (the core complexity):**
- Messages form a **tree** (via `uuid`/`parentUuid`), not a flat list — retries and interrupts create branches
- Algorithm:
  1. Read all lines, filter to `type` in ("user", "assistant"), skip `isApiErrorMessage=True`
  2. Build `uuid → message` map and `parentUuid → [children]` map
  3. Walk from root (`parentUuid` is null) choosing the last non-sidechain child at each step → produces linear conversation path
  4. Group consecutive assistant messages into single turns (thinking + text + tool_use)
  5. Match `tool_use` blocks to `tool_result` entries via `tool_use_id`

**Data model:**
```python
@dataclass
class ToolCall:
    name: str           # "Bash", "Read", "Edit", etc.
    input: dict
    result: str | None
    is_error: bool

@dataclass
class Message:
    role: str           # "user" | "assistant"
    timestamp: str
    text: str | None    # markdown text content
    tool_calls: list[ToolCall]

@dataclass
class Session:
    session_id: str
    project: str
    started_at: str
    messages: list[Message]
```

### Step 3: HTML template (`template.html`)

Self-contained HTML with all CSS inlined. Design inspired by ChatGPT shared chats:
- Clean centered layout (max-width ~48rem)
- User messages: subtle background, distinct from assistant
- Assistant messages: white background with rendered markdown
- Code blocks: dark background with Pygments syntax highlighting
- Tool calls: `<details>` elements (collapsed by default) showing tool name + brief summary line
  - Bash → show command; Read → show file path; Edit → show file path; Grep → show pattern
- Large tool results (>100 lines): truncated with CSS `max-height` + "Show more" toggle
- Header with project name, session date, "Exported from Claude Code"

### Step 4: HTML renderer (`renderer.py`)

- Load `template.html` as Jinja2 template
- Convert assistant text content from Markdown → HTML using `markdown` library with `fenced_code`, `codehilite`, `tables` extensions
- Inline Pygments CSS for syntax highlighting
- Render tool call summaries (truncated command/path per tool type)
- Auto-escape tool results to prevent XSS
- Write final self-contained HTML file

### Step 5: CLI wiring (`cli.py`)

- argparse with the interface described above
- Wire together: discover session → parse JSONL → render HTML → optionally upload gist
- Helpful error messages for common issues (session not found, no sessions, etc.)

### Step 6: Gist integration (`gist.py`)

- Check `gh` CLI is installed, give installation instructions if not
- `gh gist create --public --filename index.html <path>` → parse gist URL from stdout
- Print shareable URL: `https://gisthost.github.io/?{GIST_ID}`
- This is optional — the tool works fully without `gh`

## Key Design Decisions

- **Python** — good JSONL/JSON handling, markdown library ecosystem, easy CLI packaging
- **Jinja2 template** — keeps HTML design separate from logic, easy to iterate on styling
- **Tree walk for conversation reconstruction** — handles retries, interrupts, and branches correctly
- **`<details>` for tool calls** — keeps the page scannable while preserving full information
- **`gh` CLI for gists** — avoids needing a GitHub API token; user likely already has `gh` authenticated
- **No JS framework** — pure HTML/CSS with minimal vanilla JS (just copy buttons on code blocks)

## Verification

1. Install: `pip install -e .` from project root
2. Run `get-cc-chat --list` — should show recent Claude Code sessions
3. Run `get-cc-chat` — should produce an HTML file for the most recent session
4. Open the HTML file in a browser — verify conversation renders correctly with proper formatting, collapsed tool calls, syntax-highlighted code
5. Run `get-cc-chat --gist` — should create a Gist and print a gisthost URL (requires `gh` CLI)
6. Open the gisthost URL in browser — should render the same HTML
