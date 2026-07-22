from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ApprovalPolicy, SandboxMode, Settings
from .models import CodexTurn


class CodexClient(Protocol):
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
    """Long-lived MCP client for the official `codex mcp-server` process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._start_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()

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
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def _ensure_started(self) -> ClientSession:
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
                    ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(
                            seconds=self.settings.codex_timeout_seconds
                        ),
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

    async def _call(self, name: str, arguments: dict[str, object]) -> CodexTurn:
        session = await self._ensure_started()
        async with self._call_lock:
            result = await session.call_tool(name, arguments)

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

        return CodexTurn(thread_id=thread_id, content=content, raw=payload)
