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

_RUNTIME_INSTRUCTIONS = """\
Do not request command approval or sandbox escalation.
Keep temporary files, test caches, and generated artifacts inside the provided working directory.
If a command cannot run within the configured sandbox, report the blocked command instead of
retrying outside the sandbox.
"""


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
    """Short-lived MCP client for the official ``codex mcp-server`` process.

    A fresh stdio transport is opened for every Codex turn and closed before that
    turn returns. AnyIO cancel scopes created by ``stdio_client`` are therefore
    entered and exited by the same asyncio task.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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
        if approval_policy != "never":
            raise ValueError(
                "Codex Bridge currently requires approval_policy='never' because "
                "interactive approval events cannot be answered through the tunnel."
            )

        instructions = "\n".join(
            part for part in (developer_instructions.strip(), _RUNTIME_INSTRUCTIONS.strip()) if part
        )
        arguments: dict[str, object] = {
            "prompt": prompt,
            "cwd": cwd,
            "sandbox": sandbox,
            "approval-policy": "never",
            "developer-instructions": instructions,
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
        """Compatibility hook for the application lifespan.

        Per-turn transports are already closed before public methods return, so
        there is no long-lived AnyIO context to close during server shutdown.
        """

    async def _call(self, name: str, arguments: dict[str, object]) -> CodexTurn:
        async with self._call_lock:
            result = await self._call_once(name, arguments)

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

    async def _call_once(self, name: str, arguments: dict[str, object]) -> object:
        parameters = StdioServerParameters(
            command=self.settings.codex_command,
            args=self.settings.codex_argv,
            env=os.environ.copy(),
        )

        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(parameters))
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

            return await session.call_tool(name, arguments)
