# Codex event handling and observability

The official `codex mcp-server` emits a non-standard JSON-RPC notification named
`codex/event`. A stock Python MCP `ClientSession` validates server notifications only
against the standard MCP union and logs a large Pydantic error for every Codex event.
The tool call still completes, but the useful event stream is lost and logs may contain
full command output, diffs, or encrypted reasoning payloads.

This bridge uses `CodexClientSession`, which extends the accepted notification union with
`CodexEventNotification`. Standard MCP notifications retain their original handling.
Codex events are normalized into compact `CodexEvent` records and attached to the active
bridge session.

Captured fields include:

- event type, thread, turn, status, and timestamp;
- command, working directory, exit code, duration, and bounded output previews;
- changed file names and diff size without storing the full diff;
- token usage, context window, and rate-limit usage;
- tool names and bounded input previews.

The bridge deliberately excludes raw encrypted reasoning, internal passthrough metadata,
and full unbounded payloads. Common API-key and authorization patterns are redacted before
an event is stored. Runtime logs contain only event type and identifiers.

Use the MCP tool `codex_get_events` to inspect recent normalized events. The number of
stored events and the maximum text size are controlled by:

```dotenv
BRIDGE_MAX_EVENT_TEXT_CHARS=2000
BRIDGE_MAX_SESSION_EVENTS=50
```

## Context budgets

Project memory is clipped before it is injected into Codex. Responses and long-lived
threads are bounded as well:

```dotenv
BRIDGE_MAX_MEMORY_CONTEXT_CHARS=12000
BRIDGE_MAX_CODEX_RESPONSE_CHARS=12000
BRIDGE_MAX_SESSION_TURNS=20
```

When a thread reaches the configured turn limit, start a new Codex task and rely on durable
project memory for continuity. This prevents unrelated work from accumulating in one large
context.

## Verification boundary

`codex_complete_task` requires verification evidence. Use `verification_status="passed"`
when tests or checks succeeded. Use `verification_status="not_required"` only for work such
as a read-only inspection, and explain why verification was not applicable in the
`verification` field.
