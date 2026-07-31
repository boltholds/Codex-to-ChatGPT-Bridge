# Agent instructions

## Scope

This repository implements a narrow MCP bridge around the official `codex mcp-server`.
Keep the bridge auditable, local-first, and conservative with permissions.

## Engineering rules

- Do not add shell execution outside the Codex MCP client.
- Never expose `danger-full-access` through public bridge tools.
- Resolve and validate every requested working directory against configured allowed roots.
- Treat Codex output as unverified until the coordinator records a verified completion.
- Keep memory records append-only. Corrections should supersede prior records instead of rewriting history.
- Avoid logging secrets, API keys, environment variables, or full authentication payloads.
- Add unit tests for permission boundaries, session persistence, and memory retrieval.
- Do not commit `.bridge/`, `.env`, Codex auth files, or repository secrets.
