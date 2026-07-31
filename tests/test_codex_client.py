import asyncio

import anyio
import pytest

from codex_chatgpt_bridge import server
from codex_chatgpt_bridge.codex_client import CodexMCPClient
from codex_chatgpt_bridge.codex_events import CodexEventNotification
from codex_chatgpt_bridge.config import Settings


@pytest.mark.asyncio
async def test_lifespan_starts_and_closes_codex_in_same_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        allowed_roots=(tmp_path,),
        memory_path=tmp_path / "memory.jsonl",
        sessions_path=tmp_path / "sessions.json",
    )

    class FakeCodex:
        def __init__(self) -> None:
            self.start_task = None
            self.close_task = None

        async def start(self) -> None:
            self.start_task = asyncio.current_task()

        async def close(self) -> None:
            self.close_task = asyncio.current_task()

    fake = FakeCodex()
    monkeypatch.setattr(server, "Settings", lambda: settings)
    monkeypatch.setattr(server, "CodexMCPClient", lambda _: fake)

    async with server.lifespan(server.mcp) as context:
        assert context.codex is fake
        assert fake.start_task is asyncio.current_task()
        assert fake.close_task is None

    assert fake.close_task is fake.start_task


@pytest.mark.asyncio
async def test_stream_deltas_are_counted_but_not_stored(tmp_path) -> None:
    settings = Settings(_env_file=None, allowed_roots=(tmp_path,))
    client = CodexMCPClient(settings)
    client._active_events = []
    client._suppressed_event_counts = {}

    delta = CodexEventNotification.model_validate(
        {
            "method": "codex/event",
            "params": {
                "_meta": {"threadId": "thread-1"},
                "msg": {
                    "type": "agent_message_content_delta",
                    "turn_id": "turn-1",
                    "delta": "hello",
                },
            },
        }
    )
    completed = CodexEventNotification.model_validate(
        {
            "method": "codex/event",
            "params": {
                "_meta": {"threadId": "thread-1"},
                "msg": {
                    "type": "task_complete",
                    "turn_id": "turn-1",
                },
            },
        }
    )

    await client._handle_codex_event(delta)
    await client._handle_codex_event(delta)
    await client._handle_codex_event(completed)

    assert client._suppressed_event_counts == {"agent_message_content_delta": 2}
    assert [event.event_type for event in client._active_events] == ["task_complete"]


@pytest.mark.asyncio
async def test_close_ignores_expected_closed_stdio_group(tmp_path) -> None:
    settings = Settings(_env_file=None, allowed_roots=(tmp_path,))
    client = CodexMCPClient(settings)

    class ClosedStack:
        async def aclose(self) -> None:
            raise BaseExceptionGroup(
                "stdio already closed",
                [anyio.BrokenResourceError()],
            )

    client._stack = ClosedStack()  # type: ignore[assignment]

    await client.close()

    assert client._stack is None
    assert client._session is None


@pytest.mark.asyncio
async def test_close_reraises_unexpected_shutdown_error(tmp_path) -> None:
    settings = Settings(_env_file=None, allowed_roots=(tmp_path,))
    client = CodexMCPClient(settings)

    class FailingStack:
        async def aclose(self) -> None:
            raise ExceptionGroup("unexpected shutdown", [RuntimeError("boom")])

    client._stack = FailingStack()  # type: ignore[assignment]

    with pytest.raises(ExceptionGroup, match="unexpected shutdown"):
        await client.close()
