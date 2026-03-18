# get-cc-chat

Export Claude Code terminal sessions as shareable HTML pages.

## Install

```
pipx install .
```

## Usage

```
get-cc-chat                    # export most recent session
get-cc-chat abc12345           # export specific session (prefix match)
get-cc-chat --list             # list recent sessions
get-cc-chat --gist             # upload to GitHub Gist, print shareable URL
get-cc-chat --no-tools         # omit tool call details
get-cc-chat --project /path    # filter by project directory
get-cc-chat --output chat.html # custom output path
```

## Features

- Parses Claude Code's JSONL conversation tree, handling parallel tool calls, retries, and sidechains
- Renders markdown with syntax-highlighted code blocks (Pygments monokai theme)
- Tool calls shown as collapsible `<details>` elements with smart summaries
- Self-contained HTML output — no external dependencies
- Optional GitHub Gist upload via `gh` CLI for instant sharing

## Development

```
pip install -e .
pytest tests/ -v
```

## CC Session used for this project (and example of tool)
https://gisthost.github.io/?90c933f6b71b1f6a3dc1c435bf8b672c