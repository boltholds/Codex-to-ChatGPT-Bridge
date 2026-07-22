# Codex-to-ChatGPT Bridge

A local-first MCP bridge that lets ChatGPT coordinate Codex CLI sessions while both agents use the same durable project memory.

The bridge wraps the official `codex mcp-server`, preserves Codex `threadId` values, validates repository paths, injects relevant memory into new and continued turns, and stores reviewed results separately from unverified agent output.

## First vertical slice

Implemented MCP tools:

- `bridge_health`
- `memory_record`
- `memory_search`
- `codex_start_task`
- `codex_continue_task`
- `codex_get_session`
- `codex_list_sessions`
- `codex_complete_task`

State is stored locally:

```text
.bridge/
├── memory.jsonl
└── sessions.json
```

Memory is append-only JSONL. Codex responses are saved as unverified episodes. A coordinator records a verified result only after reviewing the diff and checks.

## Architecture

```text
ChatGPT / MCP client
        |
        v
Codex-to-ChatGPT Bridge
  |                 |
  v                 v
shared memory    Codex MCP client
(JSONL MVP)          |
                     v
              codex mcp-server
                     |
                     v
            allowed Git repositories
```

The JSONL backend is intentionally replaceable. A later adapter can point the same service contract at Omni-Memory without changing the public MCP tools.

## Requirements

- Python 3.11+
- Codex CLI installed and authenticated
- `codex` available on `PATH`
- MCP Python SDK 1.27.x (`<2` is pinned until the v2 migration)
- Git repositories located under explicitly allowed roots

Codex exposes `codex` for starting a thread and `codex-reply` for continuing it. This bridge uses those tools instead of parsing terminal output.

## Install

```bash
git clone https://github.com/boltholds/Codex-to-ChatGPT-Bridge.git
cd Codex-to-ChatGPT-Bridge
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `BRIDGE_ALLOWED_ROOTS` to a JSON array of directories containing repositories that Codex may access.

Windows example:

```dotenv
BRIDGE_ALLOWED_ROOTS=["C:\\Users\\bolthold\\Documents\\Code"]
BRIDGE_CODEX_TIMEOUT_SECONDS=21600
```

## Run over stdio

```bash
codex-chatgpt-bridge
```

or:

```bash
python -m codex_chatgpt_bridge
```

Inspect the server:

```bash
npx -y @modelcontextprotocol/inspector python -m codex_chatgpt_bridge
```

## MCP client configuration

Example project-scoped Codex/ChatGPT desktop MCP configuration:

```toml
[mcp_servers.codex_bridge]
command = "C:\\path\\to\\Codex-to-ChatGPT-Bridge\\.venv\\Scripts\\python.exe"
args = ["-m", "codex_chatgpt_bridge"]
cwd = "C:\\path\\to\\Codex-to-ChatGPT-Bridge"

[mcp_servers.codex_bridge.env]
BRIDGE_ALLOWED_ROOTS = '["C:\\\\Users\\\\bolthold\\\\Documents\\\\Code"]'
```

For a Unix host, use the virtual environment's `bin/python` path.

## Typical workflow

1. Call `memory_search` for the project.
2. Call `codex_start_task` with the project, objective, and repository `cwd`.
3. Review `last_response`, repository diff, and tests.
4. Call `codex_continue_task` with corrections.
5. After independent review, call `codex_complete_task` to store a verified result.

Example start request:

```json
{
  "project": "Gefest CAD",
  "objective": "Implement structured solver diagnostics and tests",
  "cwd": "C:\\Users\\bolthold\\Documents\\Code\\Gefest-CAD",
  "repository": "boltholds/Gefest-CAD",
  "branch": "feat/solver-diagnostics",
  "sandbox": "workspace-write",
  "approval_policy": "never"
}
```

## Safety boundary

- Public tools expose only `read-only` and `workspace-write` sandboxes.
- Every `cwd` is resolved and checked against `BRIDGE_ALLOWED_ROOTS`.
- The bridge does not implement arbitrary shell execution.
- Codex is instructed not to commit, push, read secrets, or leave the working directory unless the task explicitly requires it.
- `.bridge`, `.env`, and authentication files are ignored by Git.
- `danger-full-access` requires a future isolated runner design and is deliberately absent.

## Development

```bash
pytest
ruff check .
```

The unit tests use a fake Codex client, so they do not require a live Codex session.
