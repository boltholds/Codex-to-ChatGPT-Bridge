from pathlib import Path

import pytest

from codex_chatgpt_bridge.config import Settings
from codex_chatgpt_bridge.models import CodexEvent, CodexTurn, MemoryRecord
from codex_chatgpt_bridge.service import BridgeService
from codex_chatgpt_bridge.storage import MemoryStore, SessionStore


class FakeCodexClient:
    def __init__(self) -> None:
        self.started_prompt = ""
        self.continued_prompt = ""

    async def start_turn(self, **kwargs: object) -> CodexTurn:
        self.started_prompt = str(kwargs["prompt"])
        return CodexTurn(
            thread_id="thread-1",
            content="Initial inspection complete.",
            events=[
                CodexEvent(
                    event_type="token_count",
                    thread_id="thread-1",
                    details={
                        "total_token_usage": {"total_tokens": 120},
                        "rate_limit_used_percent": 10.0,
                    },
                )
            ],
        )

    async def continue_turn(self, **kwargs: object) -> CodexTurn:
        self.continued_prompt = str(kwargs["prompt"])
        return CodexTurn(thread_id="thread-1", content="Tests pass.")

    async def close(self) -> None:
        return None


def make_service(
    tmp_path: Path,
    allowed_root: Path,
    **settings_overrides: object,
) -> tuple[BridgeService, FakeCodexClient]:
    settings = Settings(
        allowed_roots=(allowed_root,),
        memory_path=tmp_path / "memory.jsonl",
        sessions_path=tmp_path / "sessions.json",
        **settings_overrides,
    )
    codex = FakeCodexClient()
    return (
        BridgeService(
            settings=settings,
            codex=codex,
            memory=MemoryStore(settings.memory_path),
            sessions=SessionStore(settings.sessions_path),
        ),
        codex,
    )


@pytest.mark.asyncio
async def test_start_task_injects_matching_memory(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    service, codex = make_service(tmp_path, tmp_path)
    await service.memory.append(
        MemoryRecord(
            project="Bridge",
            kind="constraint",
            content="Never expose danger-full-access.",
            source="user",
            verified=True,
        )
    )

    session = await service.start_task(
        project="Bridge",
        objective="Implement permission validation",
        cwd=str(repository),
    )

    assert session.thread_id == "thread-1"
    assert "Never expose danger-full-access" in codex.started_prompt
    assert "Implement permission validation" in codex.started_prompt
    assert session.last_event_type == "token_count"
    assert session.token_usage == {"total_tokens": 120}
    assert session.rate_limit_used_percent == 10.0


@pytest.mark.asyncio
async def test_rejects_working_directory_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    service, _ = make_service(tmp_path, allowed)

    with pytest.raises(PermissionError):
        await service.start_task(
            project="Bridge",
            objective="Do work",
            cwd=str(outside),
        )


@pytest.mark.asyncio
async def test_complete_task_writes_verified_result(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    service, _ = make_service(tmp_path, tmp_path)
    session = await service.start_task(
        project="Bridge",
        objective="Add memory",
        cwd=str(repository),
    )

    completed = await service.complete_task(
        session_id=session.session_id,
        summary="Memory added.",
        commit_sha="abc123",
        verification="pytest: passed",
    )

    assert completed.status == "completed"
    assert completed.verification_status == "passed"
    hits = await service.memory.search(
        project="Bridge",
        kind="result",
        verified_only=True,
    )
    assert len(hits) == 1
    assert hits[0].record.commit_sha == "abc123"


@pytest.mark.asyncio
async def test_complete_task_requires_verification_evidence(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    service, _ = make_service(tmp_path, tmp_path)
    session = await service.start_task(
        project="Bridge",
        objective="Inspect code",
        cwd=str(repository),
    )

    with pytest.raises(ValueError, match="Verification evidence"):
        await service.complete_task(
            session_id=session.session_id,
            summary="Inspection complete.",
            verification="",
        )


@pytest.mark.asyncio
async def test_continue_task_enforces_turn_limit(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    service, _ = make_service(tmp_path, tmp_path, max_session_turns=1)
    session = await service.start_task(
        project="Bridge",
        objective="Inspect code",
        cwd=str(repository),
    )

    with pytest.raises(ValueError, match="start a new Codex thread"):
        await service.continue_task(
            session_id=session.session_id,
            instruction="Continue",
        )


@pytest.mark.asyncio
async def test_memory_context_is_bounded(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    service, codex = make_service(
        tmp_path,
        tmp_path,
        max_memory_context_chars=1_000,
    )
    for index in range(5):
        await service.memory.append(
            MemoryRecord(
                project="Bridge",
                kind="note",
                content=f"record-{index} " + ("x" * 700),
                source="user",
            )
        )

    await service.start_task(
        project="Bridge",
        objective="Use project context",
        cwd=str(repository),
    )

    durable_context = codex.started_prompt.split("Durable project context:\n", 1)[1]
    durable_context = durable_context.split("\n\nBegin by inspecting", 1)[0]
    assert len(durable_context) <= 1_000
