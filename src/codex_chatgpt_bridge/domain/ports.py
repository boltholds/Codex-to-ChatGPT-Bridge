from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..config import ApprovalPolicy, SandboxMode
from ..models import BridgeSession, CodexTurn, MemoryHit, MemoryKind, MemoryRecord, SessionStatus


class CodexExecution(Protocol):
    async def start_turn(self, *, prompt: str, cwd: str, sandbox: SandboxMode,
                         approval_policy: ApprovalPolicy, developer_instructions: str,
                         model: str | None = None) -> CodexTurn: ...
    async def continue_turn(self, *, thread_id: str, prompt: str) -> CodexTurn: ...
    async def close(self) -> None: ...


class MemoryRepository(Protocol):
    async def append(self, record: MemoryRecord) -> MemoryRecord: ...
    async def get(self, memory_id: UUID) -> MemoryRecord | None: ...
    async def search(self, *, project: str, query: str = "", limit: int = 10,
                     kind: MemoryKind | None = None,
                     verified_only: bool = False) -> list[MemoryHit]: ...


class SessionRepository(Protocol):
    async def upsert(self, session: BridgeSession) -> BridgeSession: ...
    async def get(self, session_id: UUID) -> BridgeSession | None: ...
    async def list(self, *, project: str | None = None,
                   status: SessionStatus | None = None,
                   limit: int = 20) -> list[BridgeSession]: ...


class UnitOfWork(Protocol):
    async def commit_completion(self, session: BridgeSession,
                                memory: MemoryRecord) -> None: ...


class FileRepository(Protocol):
    path: Path
