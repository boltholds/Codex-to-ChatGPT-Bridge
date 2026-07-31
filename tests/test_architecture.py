from pathlib import Path

import pytest

from codex_chatgpt_bridge.domain.policies import (
    select_approval_policy,
    select_sandbox,
)
from codex_chatgpt_bridge.domain.session_state import transition
from codex_chatgpt_bridge.infrastructure.file_unit_of_work import FileUnitOfWork
from codex_chatgpt_bridge.infrastructure.json_memory_repository import JsonMemoryRepository
from codex_chatgpt_bridge.infrastructure.json_session_repository import JsonSessionRepository
from codex_chatgpt_bridge.models import BridgeSession, MemoryRecord
from codex_chatgpt_bridge.storage import MemoryStore, SessionStore


def test_policy_defaults_and_validation() -> None:
    assert select_sandbox(None, "read-only") == "read-only"
    assert select_approval_policy(None, "never") == "never"
    with pytest.raises(ValueError):
        select_sandbox("danger-full-access", "read-only")  # type: ignore[arg-type]


def test_state_machine_allows_only_active_terminal_transitions() -> None:
    completed = BridgeSession(thread_id="t", project="p", cwd=".", objective="o")
    transition(completed, "completed")
    with pytest.raises(ValueError):
        transition(completed, "failed")
    failed = BridgeSession(thread_id="t", project="p", cwd=".", objective="o")
    assert transition(failed, "failed").status == "failed"


@pytest.mark.asyncio
async def test_file_uow_rolls_back_session_when_memory_append_fails(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path / "sessions.json")
    memory = MemoryStore(tmp_path / "memory.jsonl")
    session = BridgeSession(thread_id="t", project="p", cwd=".", objective="o")
    await sessions.upsert(session)
    original = (tmp_path / "sessions.json").read_bytes()
    session.status = "completed"

    async def fail(_: MemoryRecord) -> MemoryRecord:
        raise OSError("disk full")

    memory.append = fail  # type: ignore[method-assign]
    uow = FileUnitOfWork(sessions, memory)
    with pytest.raises(OSError, match="disk full"):
        await uow.commit_completion(
            session,
            MemoryRecord(project="p", kind="result", content="done", source="chatgpt"),
        )

    assert (tmp_path / "sessions.json").read_bytes() == original
    assert not (tmp_path / "memory.jsonl").exists()


@pytest.mark.asyncio
async def test_json_adapters_read_legacy_persisted_formats(tmp_path: Path) -> None:
    legacy_sessions = SessionStore(tmp_path / "sessions.json")
    legacy_memory = MemoryStore(tmp_path / "memory.jsonl")
    session = await legacy_sessions.upsert(
        BridgeSession(thread_id="t", project="p", cwd=".", objective="o")
    )
    record = await legacy_memory.append(
        MemoryRecord(project="p", kind="fact", content="legacy", source="user")
    )

    assert (await JsonSessionRepository(legacy_sessions.path).get(session.session_id)) == session
    assert (await JsonMemoryRepository(legacy_memory.path).get(record.id)) == record
