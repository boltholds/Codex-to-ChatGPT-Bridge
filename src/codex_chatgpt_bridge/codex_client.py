from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Protocol

import anyio
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

from .codex_events import (
    CodexClientSession,
    CodexEventNotification,
    normalize_codex_event,
)
from .config import ApprovalPolicy, SandboxMode, Settings
from .models import CodexEvent, CodexTurn

logger = logging.getLogger(__name__)

_EXPECTED_STDIO_SHUTDOWN_ERRORS = (
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
    anyio.EndOfStream,
    BrokenPipeError,
)


class CodexClient(Protocol):
    async def start(self) -> None: ...

    async def start_turn(
        self,
        *,
        prompt: str,
        cwd: str,
        sandbox: SandboxMode,
        approval_policy: ApprovalPolicy,
        developer_instructions: str,
        model: str | None = None,
    ) -> CodexTurn: ...

    async def continue_turn(self, *, thread_id: str, prompt: str) -> CodexTurn: ...

    async def close(self) -> None: ...


class CodexMCPClient:
    """Long-lived MCP client for the official `codex mcp-server` process.

    The MCP stdio contexts are task-affine because the SDK uses AnyIO cancel scopes.
    `start()` and `close()` must therefore be called by the same owner task. The FastMCP
    lifespan owns that task; request handlers only call the already-started session.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stack: AsyncExitStack | None = None
        self._session: CodexClientSession | None = None
        self._start_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self._active_events: list[CodexEvent] | None = None
        self._suppressed_event_counts: dict[str, int] | None = None

    async def start(self) -> None:
        """Start and validate the nested Codex MCP server in the owner task."""
        await self._ensure_started()

    async def start_turn(
        self,
        *,
        prompt: str,
        cwd: str,
        sandbox: SandboxMode,
        approval_policy: ApprovalPolicy,
        developer_instructions: str,
        model: str | None = None,
    ) -> CodexTurn:
        arguments: dict[str, object] = {
            "prompt": prompt,
            "cwd": cwd,
            "sandbox": sandbox,
            "approval-policy": approval_policy,
            "developer-instructions": developer_instructions,
        }
        if model:
            arguments["model"] = model
        return await self._call("codex", arguments)

    async def continue_turn(self, *, thread_id: str, prompt: str) -> CodexTurn:
        return await self._call(
            "codex-reply",
            {"threadId": thread_id, "prompt": prompt},
        )

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        self._active_events = None
        self._suppressed_event_counts = None
        if stack is None:
            return

        try:
            await stack.aclose()
        except BaseException as exc:
            if _is_expected_stdio_shutdown_error(exc):
                logger.info(
                    "codex_stdio_already_closed_during_shutdown error=%s",
                    type(exc).__name__,
                )
                return
            raise

    async def _ensure_started(self) -> CodexClientSession:
        if self._session is not None:
            return self._session

        async with self._start_lock:
            if self._session is not None:
                return self._session

            stack = AsyncExitStack()
            try:
                parameters = StdioServerParameters(
                    command=self.settings.codex_command,
                    args=self.settings.codex_argv,
                    env=os.environ.copy(),
                )
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(parameters)
                )
                session = await stack.enter_async_context(
                    CodexClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(
                            seconds=self.settings.codex_timeout_seconds
                        ),
                        codex_event_handler=self._handle_codex_event,
                    )
                )
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                required = {"codex", "codex-reply"}
                if not required.issubset(names):
                    missing = ", ".join(sorted(required - names))
                    raise RuntimeError(f"Codex MCP server is missing tools: {missing}")
            except Exception:
                await stack.aclose()
                raise

            self._stack = stack
            self._session = session
            return session

    async def _handle_codex_event(
        self,
        notification: CodexEventNotification,
    ) -> None:
        event = normalize_codex_event(
            notification,
            max_text_chars=self.settings.max_event_text_chars,
        )

        # Token-by-token deltas are useful for an interactive UI, but storing and logging
        # each one makes a normal response produce hundreds of duplicate lines. The final
        # agent_message/item_completed events retain the useful content.
        if event.event_type.endswith("_delta"):
            if self._suppressed_event_counts is not None:
                count = self._suppressed_event_counts.get(event.event_type, 0)
                self._suppressed_event_counts[event.event_type] = count + 1
            logger.debug(
                "codex_stream_delta type=%s thread=%s turn=%s",
                event.event_type,
                event.thread_id or "-",
                event.turn_id or "-",
            )
            return

        if self._active_events is not None:
            self._active_events.append(event)
        logger.info(
            "codex_event type=%s thread=%s turn=%s status=%s",
            event.event_type,
            event.thread_id or "-",
            event.turn_id or "-",
            event.status or "-",
        )

    async def _call(self, name: str, arguments: dict[str, object]) -> CodexTurn:
        session = await self._ensure_started()
        async with self._call_lock:
            self._active_events = []
            self._suppressed_event_counts = {}
            try:
                result = await session.call_tool(name, arguments)
                events = list(self._active_events)
                suppressed_counts = dict(self._suppressed_event_counts)
            finally:
                self._active_events = None
                self._suppressed_event_counts = None

        if suppressed_counts:
            events.insert(
                0,
                CodexEvent(
                    event_type="stream_deltas_suppressed",
                    details={
                        "counts": dict(sorted(suppressed_counts.items())),
                        "total": sum(suppressed_counts.values()),
                    },
                ),
            )

        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        structured = payload.get("structuredContent") or payload.get("structured_content") or {}
        if not isinstance(structured, dict):
            structured = {}

        thread_id = structured.get("threadId") or structured.get("thread_id")
        content = structured.get("content")

        if not content:
            text_parts: list[str] = []
            raw_content = payload.get("content", [])
            if isinstance(raw_content, list):
                for item in raw_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
            content = "\n".join(text_parts)

        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError(f"Codex response did not contain a threadId: {payload}")
        if not isinstance(content, str):
            content = str(content or "")

        compact_raw: dict[str, object] = {
            "is_error": bool(payload.get("isError", False)),
            "structured_content": structured,
        }
        return CodexTurn(
            thread_id=thread_id,
            content=content,
            events=events,
            raw=compact_raw,
        )


def _is_expected_stdio_shutdown_error(exc: BaseException) -> bool:
    """Return true only when every leaf is an expected closed-pipe condition."""
    if isinstance(exc, BaseExceptionGroup):
        return bool(exc.exceptions) and all(
            _is_expected_stdio_shutdown_error(child) for child in exc.exceptions
        )
    return isinstance(exc, _EXPECTED_STDIO_SHUTDOWN_ERRORS)
