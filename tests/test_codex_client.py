from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import codex_chatgpt_bridge.codex_client as codex_client_module
from codex_chatgpt_bridge.codex_client import CodexMCPClient
from codex_chatgpt_bridge.config import Settings


class FakeResult:
    def __init__(self, thread_id: str, content: str) -> None:
        self.thread_id = thread_id
        self.content = content

    def model_dump(self, **_: Any) -> dict[str, object]:
        return {
            "structuredContent": {
                "threadId": self.thread_id,
                "content": self.content,
            }
        }


class FakeStdioContext:
    def __init__(self, events: list[tuple[str, asyncio.Task[Any] | None]]) -> None:
        self.events = events

    async def __aenter__(self) -> tuple[object, object]:
        self.events.append(("stdio-enter", asyncio.current_task()))
        return object(), object()

    async def __aexit__(self, *_: object) -> None:
        self.events.append(("stdio-exit", asyncio.current_task()))


class FakeSession:
    instances: list[FakeSession] = []
    events: list[tuple[str, asyncio.Task[Any] | None]] = []

    def __init__(self, *_: object, **__: object) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.__class__.instances.append(self)

    async def __aenter__(self) -> FakeSession:
        self.events.append(("session-enter", asyncio.current_task()))
        return self

    async def __aexit__(self, *_: object) -> None:
        self.events.append(("session-exit", asyncio.current_task()))

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[SimpleNamespace(name="codex"), SimpleNamespace(name="codex-reply")]
        )

    async def call_tool(self, name: str, arguments: dict[str, object]) -> FakeResult:
        self.calls.append((name, arguments))
        if name == "codex":
            return FakeResult("thread-started", "started")
        return FakeResult(str(arguments["threadId"]), "continued")


@pytest.fixture(autouse=True)
def reset_fakes() -> None:
    FakeSession.instances = []
    FakeSession.events = []


@pytest.mark.asyncio
async def test_each_turn_opens_and_closes_transport_in_same_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, asyncio.Task[Any] | None]] = []

    monkeypatch.setattr(
        codex_client_module,
        "stdio_client",
        lambda _: FakeStdioContext(events),
    )
    monkeypatch.setattr(codex_client_module, "ClientSession", FakeSession)

    client = CodexMCPClient(Settings())
    started = await client.start_turn(
        prompt="inspect",
        cwd=".",
        sandbox="read-only",
        approval_policy="never",
        developer_instructions="Stay scoped.",
    )
    continued = await client.continue_turn(
        thread_id=started.thread_id,
        prompt="continue",
    )
    await client.close()

    assert started.thread_id == "thread-started"
    assert continued.thread_id == "thread-started"
    assert len(FakeSession.instances) == 2

    stdio_tasks = [task for _, task in events]
    session_tasks = [task for _, task in FakeSession.events]
    assert len(stdio_tasks) == 4
    assert len(session_tasks) == 4
    assert len(set(stdio_tasks + session_tasks)) == 1


@pytest.mark.asyncio
async def test_start_turn_rejects_interactive_approval_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = False

    def fail_if_started(_: object) -> FakeStdioContext:
        nonlocal started
        started = True
        return FakeStdioContext([])

    monkeypatch.setattr(codex_client_module, "stdio_client", fail_if_started)

    client = CodexMCPClient(Settings())
    with pytest.raises(ValueError, match="approval_policy='never'"):
        await client.start_turn(
            prompt="inspect",
            cwd=".",
            sandbox="read-only",
            approval_policy="on-request",
            developer_instructions="Stay scoped.",
        )

    assert started is False


@pytest.mark.asyncio
async def test_runtime_instructions_forbid_escalation_and_external_temp_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, asyncio.Task[Any] | None]] = []

    monkeypatch.setattr(
        codex_client_module,
        "stdio_client",
        lambda _: FakeStdioContext(events),
    )
    monkeypatch.setattr(codex_client_module, "ClientSession", FakeSession)

    client = CodexMCPClient(Settings())
    await client.start_turn(
        prompt="inspect",
        cwd=".",
        sandbox="workspace-write",
        approval_policy="never",
        developer_instructions="Stay scoped.",
    )

    _, arguments = FakeSession.instances[0].calls[0]
    instructions = str(arguments["developer-instructions"])
    assert arguments["approval-policy"] == "never"
    assert "Do not request command approval or sandbox escalation" in instructions
    assert "inside the provided working directory" in instructions
