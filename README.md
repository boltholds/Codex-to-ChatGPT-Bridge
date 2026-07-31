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
- Optional: OpenAI `tunnel-client.exe` for connecting cloud ChatGPT to the local stdio server

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

## Connect ChatGPT through Secure MCP Tunnel on Windows

The tunnel keeps the bridge and Codex CLI on the local machine. `tunnel-client.exe` opens an outbound connection to OpenAI and launches this bridge as a private stdio MCP subprocess.

### 1. Create the tunnel and runtime key

1. Create a tunnel in OpenAI Platform tunnel settings and associate it with the ChatGPT workspace that will use it.
2. Copy the tunnel ID in the form `tunnel_...`.
3. Create a runtime API key in the same Platform organization.
4. Download the current Windows `tunnel-client.exe`, for example to:

```text
C:\Users\YOUR_USER\Downloads\tunnel-client.exe
```

Do not store the runtime key in `.env` or commit it to Git.

### 2. Create the local tunnel profile

Run from PowerShell in the repository directory:

```powershell
Set-Location C:\Users\YOUR_USER\Documents\Code\Codex-to-ChatGPT-Bridge

.\scripts\setup-tunnel.ps1 `
  -TunnelId tunnel_REPLACE_ME `
  -OpenWebUi
```

The script checks:

- `.venv\Scripts\python.exe` exists;
- `.env` exists;
- the bridge package imports successfully;
- `codex` is available on `PATH`;
- `tunnel-client.exe` starts correctly.

It then creates the `codex-bridge` profile. Profiles are normally stored under:

```text
C:\Users\YOUR_USER\AppData\Roaming\tunnel-client\codex-bridge.yaml
```

If `tunnel-client.exe` is stored elsewhere, pass its absolute path:

```powershell
.\scripts\setup-tunnel.ps1 `
  -TunnelId tunnel_REPLACE_ME `
  -TunnelClient 'D:\Tools\tunnel-client.exe' `
  -OpenWebUi
```

To replace an existing profile:

```powershell
.\scripts\setup-tunnel.ps1 `
  -TunnelId tunnel_REPLACE_ME `
  -Force `
  -OpenWebUi
```

The generated stdio command uses the repository virtual environment:

```text
C:/.../Codex-to-ChatGPT-Bridge/.venv/Scripts/python.exe -m codex_chatgpt_bridge
```

### 3. Diagnose and run

Set the runtime key only in the PowerShell process that will run the tunnel:

```powershell
$env:CONTROL_PLANE_API_KEY = 'sk-REPLACE_ME'
```

Then start the tunnel:

```powershell
.\scripts\run-tunnel.ps1
```

The run script changes into the repository directory so the bridge can load `.env`, runs `doctor --explain`, then starts the `codex-bridge` profile. Keep the terminal open while ChatGPT discovers or invokes the MCP tools.

To use a non-default executable or profile:

```powershell
.\scripts\run-tunnel.ps1 `
  -Profile codex-bridge `
  -TunnelClient 'D:\Tools\tunnel-client.exe'
```

### 4. Create the ChatGPT app/plugin

While `run-tunnel.ps1` is active:

1. Open ChatGPT settings and create a developer-mode app/plugin.
2. Select **Tunnel** as the connection type.
3. Select the tunnel created for this bridge.
4. Create a new conversation with the integration enabled.
5. Call `bridge_health`, then try a read-only `codex_start_task`.

When the MCP tool schema changes, reconnect or update the app and start a new conversation so ChatGPT refreshes the tool list.

### Tunnel troubleshooting

Check the binary and quickstart help:

```powershell
& "$env:USERPROFILE\Downloads\tunnel-client.exe" --version
& "$env:USERPROFILE\Downloads\tunnel-client.exe" help quickstart
```

Run diagnostics directly:

```powershell
& "$env:USERPROFILE\Downloads\tunnel-client.exe" doctor `
  --profile codex-bridge `
  --explain
```

Common causes:

- `401 Unauthorized`: the runtime key is missing, revoked, or belongs to another Platform organization.
- Tunnel not visible in ChatGPT: the tunnel is not associated with the target ChatGPT workspace or the account lacks tunnel-use permission.
- Bridge exits immediately: run `.venv\Scripts\python.exe -m codex_chatgpt_bridge` from the repository and inspect the error.
- `codex` not found: install/authenticate Codex CLI natively on Windows and confirm `Get-Command codex` succeeds.
- `.env` ignored: start the tunnel through `scripts\run-tunnel.ps1`, which sets the repository as the child process working directory.

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
