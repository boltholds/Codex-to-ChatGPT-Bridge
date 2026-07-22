from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from uuid import UUID

from .models import BridgeSession, MemoryHit, MemoryKind, MemoryRecord, SessionStatus, utc_now

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value) if len(token) > 1}


class MemoryStore:
    """Append-only JSONL memory with deterministic lexical retrieval."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def append(self, record: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        return record

    async def get(self, memory_id: UUID) -> MemoryRecord | None:
        for record in await self._read_all():
            if record.id == memory_id:
                return record
        return None

    async def search(
        self,
        *,
        project: str,
        query: str = "",
        limit: int = 10,
        kind: MemoryKind | None = None,
        verified_only: bool = False,
    ) -> list[MemoryHit]:
        records = [
            record
            for record in await self._read_all()
            if record.project.casefold() == project.casefold()
            and (kind is None or record.kind == kind)
            and (not verified_only or record.verified)
        ]
        query_tokens = _tokens(query)

        hits: list[MemoryHit] = []
        for record in records:
            haystack = " ".join(
                [
                    record.content,
                    record.kind,
                    " ".join(record.tags),
                    record.repository or "",
                    record.task_id or "",
                    record.branch or "",
                ]
            )
            record_tokens = _tokens(haystack)
            lexical = (
                len(query_tokens & record_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            quality = (0.20 if record.verified else 0.0) + (record.confidence * 0.05)
            hits.append(MemoryHit(record=record, score=round(lexical + quality, 6)))

        if query_tokens:
            hits.sort(
                key=lambda hit: (hit.score, hit.record.created_at),
                reverse=True,
            )
        else:
            hits.sort(key=lambda hit: hit.record.created_at, reverse=True)
        return hits[:limit]

    async def _read_all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []

        records: list[MemoryRecord] = []
        async with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(MemoryRecord.model_validate_json(line))
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid memory record at {self.path}:{line_number}"
                        ) from exc
        return records


class SessionStore:
    """Small JSON session index. Codex itself remains the owner of thread state."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def upsert(self, session: BridgeSession) -> BridgeSession:
        async with self._lock:
            sessions = self._read_unlocked()
            session.updated_at = utc_now()
            sessions[str(session.session_id)] = session
            self._write_unlocked(sessions)
        return session

    async def get(self, session_id: UUID) -> BridgeSession | None:
        async with self._lock:
            return self._read_unlocked().get(str(session_id))

    async def list(
        self,
        *,
        project: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 20,
    ) -> list[BridgeSession]:
        async with self._lock:
            sessions = list(self._read_unlocked().values())
        sessions = [
            session
            for session in sessions
            if (project is None or session.project.casefold() == project.casefold())
            and (status is None or session.status == status)
        ]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions[:limit]

    def _read_unlocked(self) -> dict[str, BridgeSession]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Session store must contain a JSON object: {self.path}")
        return {
            key: BridgeSession.model_validate(value)
            for key, value in payload.items()
        }

    def _write_unlocked(self, sessions: dict[str, BridgeSession]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            key: session.model_dump(mode="json")
            for key, session in sessions.items()
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
