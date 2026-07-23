from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

MemoryKind = Literal["decision", "fact", "constraint", "episode", "result", "note"]
MemorySource = Literal["user", "chatgpt", "codex", "system"]
SessionStatus = Literal["active", "awaiting_review", "completed", "failed"]
VerificationStatus = Literal["not_run", "passed", "failed", "not_required"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project: str = Field(min_length=1, max_length=200)
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=20_000)
    source: MemorySource
    tags: list[str] = Field(default_factory=list, max_length=50)
    repository: str | None = Field(default=None, max_length=500)
    task_id: str | None = Field(default=None, max_length=200)
    branch: str | None = Field(default=None, max_length=500)
    commit_sha: str | None = Field(default=None, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verified: bool = False
    supersedes: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MemoryHit(BaseModel):
    record: MemoryRecord
    score: float = 0.0


class CodexEvent(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    thread_id: str | None = Field(default=None, max_length=200)
    turn_id: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=100)
    timestamp_ms: int | None = None
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CodexTurn(BaseModel):
    thread_id: str
    content: str
    events: list[CodexEvent] = Field(default_factory=list)
    raw: dict[str, object] = Field(default_factory=dict)


class BridgeSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    thread_id: str
    project: str
    cwd: str
    objective: str
    status: SessionStatus = "active"
    verification_status: VerificationStatus = "not_run"
    repository: str | None = None
    task_id: str | None = None
    branch: str | None = None
    memory_ids: list[UUID] = Field(default_factory=list)
    last_response: str = ""
    turn_count: int = Field(default=0, ge=0)
    last_event_type: str | None = None
    recent_events: list[CodexEvent] = Field(default_factory=list)
    token_usage: dict[str, int | float] = Field(default_factory=dict)
    rate_limit_used_percent: float | None = Field(default=None, ge=0.0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
