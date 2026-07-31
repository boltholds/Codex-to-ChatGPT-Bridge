from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .codex_client import CodexMCPClient
from .config import ApprovalPolicy, SandboxMode, Settings
from .models import (
    MemoryKind,
    MemorySource,
    SessionStatus,
    VerificationStatus,
)
from .service import BridgeService
from .storage import MemoryStore, SessionStore

_SERVER_INSTRUCTIONS = """\
Use this server to coordinate scoped Codex CLI work.
Call memory_search before starting work when project context may already exist.
Use codex_start_task for a new thread and codex_continue_task for follow-up work.
Use codex_get_events to inspect compact command, diff, token, and rate-limit events.
Never request paths outside configured roots. Treat Codex responses as unverified.
After reviewing code and checks, call codex_complete_task with verification evidence.
"""


@dataclass
class AppContext:
    service: BridgeService
    codex: CodexMCPClient


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    settings = Settings()
    codex = CodexMCPClient(settings)
    service = BridgeService(
        settings=settings,
        codex=codex,
        memory=MemoryStore(settings.memory_path),
        sessions=SessionStore(settings.sessions_path),
    )

    # The MCP SDK uses AnyIO cancel scopes inside its stdio context managers. They must
    # be entered and exited by the same task, so the lifespan task owns the nested Codex
    # process for the complete lifetime of this bridge process.
    await codex.start()
    try:
        yield AppContext(service=service, codex=codex)
    finally:
        await codex.close()


mcp = FastMCP(
    name="Codex-to-ChatGPT Bridge",
    instructions=_SERVER_INSTRUCTIONS,
    lifespan=lifespan,
    json_response=True,
)


def _service(ctx: Context[ServerSession, AppContext]) -> BridgeService:
    return ctx.request_context.lifespan_context.service


@mcp.tool()
async def bridge_health(
    ctx: Context[ServerSession, AppContext],
) -> dict[str, object]:
    """Return bridge configuration after the nested Codex MCP server is ready."""
    service = _service(ctx)
    return {
        "status": "ok",
        "codex_mcp": "ready",
        "event_adapter": "codex-event-v1",
        "codex_command": service.settings.codex_command,
        "codex_args": service.settings.codex_argv,
        "allowed_roots": [str(path) for path in service.settings.allowed_roots],
        "memory_path": str(service.settings.memory_path),
        "sessions_path": str(service.settings.sessions_path),
        "limits": {
            "memory_items": service.settings.max_memory_items,
            "memory_context_chars": service.settings.max_memory_context_chars,
            "codex_response_chars": service.settings.max_codex_response_chars,
            "event_text_chars": service.settings.max_event_text_chars,
            "session_events": service.settings.max_session_events,
            "session_turns": service.settings.max_session_turns,
        },
    }


@mcp.tool()
async def memory_record(
    project: str,
    kind: MemoryKind,
    content: str,
    ctx: Context[ServerSession, AppContext],
    source: MemorySource = "chatgpt",
    tags: list[str] | None = None,
    repository: str | None = None,
    task_id: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    confidence: float = 1.0,
    verified: bool = False,
    supersedes: str | None = None,
) -> dict[str, object]:
    """Append a durable project memory record."""
    record = await _service(ctx).record_memory(
        project=project,
        kind=kind,
        content=content,
        source=source,
        tags=tags,
        repository=repository,
        task_id=task_id,
        branch=branch,
        commit_sha=commit_sha,
        confidence=confidence,
        verified=verified,
        supersedes=UUID(supersedes) if supersedes else None,
    )
    return record.model_dump(mode="json")


@mcp.tool()
async def memory_search(
    project: str,
    ctx: Context[ServerSession, AppContext],
    query: str = "",
    limit: int = 10,
    kind: MemoryKind | None = None,
    verified_only: bool = False,
) -> list[dict[str, object]]:
    """Search durable project memory using deterministic lexical retrieval."""
    hits = await _service(ctx).search_memory(
        project=project,
        query=query,
        limit=max(1, min(limit, 50)),
        kind=kind,
        verified_only=verified_only,
    )
    return [
        {
            "score": hit.score,
            **hit.record.model_dump(mode="json"),
        }
        for hit in hits
    ]


@mcp.tool()
async def codex_start_task(
    project: str,
    objective: str,
    cwd: str,
    ctx: Context[ServerSession, AppContext],
    repository: str | None = None,
    task_id: str | None = None,
    branch: str | None = None,
    sandbox: SandboxMode | None = None,
    approval_policy: ApprovalPolicy | None = None,
    model: str | None = None,
    memory_query: str | None = None,
) -> dict[str, object]:
    """Start a scoped Codex thread and inject relevant durable memory."""
    session = await _service(ctx).start_task(
        project=project,
        objective=objective,
        cwd=cwd,
        repository=repository,
        task_id=task_id,
        branch=branch,
        sandbox=sandbox,
        approval_policy=approval_policy,
        model=model,
        memory_query=memory_query,
    )
    return session.model_dump(mode="json")


@mcp.tool()
async def codex_continue_task(
    session_id: str,
    instruction: str,
    ctx: Context[ServerSession, AppContext],
    include_memory: bool = True,
) -> dict[str, object]:
    """Continue an existing Codex thread by bridge session ID."""
    session = await _service(ctx).continue_task(
        session_id=UUID(session_id),
        instruction=instruction,
        include_memory=include_memory,
    )
    return session.model_dump(mode="json")


@mcp.tool()
async def codex_get_session(
    session_id: str,
    ctx: Context[ServerSession, AppContext],
) -> dict[str, object]:
    """Read one bridge session, including the last Codex response."""
    session = await _service(ctx).get_session(UUID(session_id))
    return session.model_dump(mode="json")


@mcp.tool()
async def codex_get_events(
    session_id: str,
    ctx: Context[ServerSession, AppContext],
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return compact normalized Codex events without raw reasoning payloads."""
    events = await _service(ctx).get_events(UUID(session_id), limit=limit)
    return [event.model_dump(mode="json") for event in events]


@mcp.tool()
async def codex_list_sessions(
    ctx: Context[ServerSession, AppContext],
    project: str | None = None,
    status: SessionStatus | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    """List recent bridge sessions."""
    sessions = await _service(ctx).list_sessions(
        project=project,
        status=status,
        limit=max(1, min(limit, 100)),
    )
    return [session.model_dump(mode="json") for session in sessions]


@mcp.tool()
async def codex_complete_task(
    session_id: str,
    summary: str,
    verification: str,
    ctx: Context[ServerSession, AppContext],
    commit_sha: str | None = None,
    verification_status: VerificationStatus = "passed",
) -> dict[str, object]:
    """Complete reviewed work only with verification evidence or an explicit exemption."""
    session = await _service(ctx).complete_task(
        session_id=UUID(session_id),
        summary=summary,
        verification=verification,
        verification_status=verification_status,
        commit_sha=commit_sha,
    )
    return session.model_dump(mode="json")
