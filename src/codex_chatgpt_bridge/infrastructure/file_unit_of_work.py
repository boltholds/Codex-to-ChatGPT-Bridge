from __future__ import annotations

import asyncio
from pathlib import Path

from ..domain.ports import MemoryRepository, SessionRepository
from ..models import BridgeSession, MemoryRecord


class FileUnitOfWork:
    """Best-effort transaction across JSON and JSONL files.

    Writes are serialized in this process. On failure, both files are restored to their
    byte-for-byte prior state. This is not crash-atomic across two files; a process or
    machine crash between replacements can still require recovery from external backup.
    """

    def __init__(self, sessions: SessionRepository, memory: MemoryRepository) -> None:
        self.sessions = sessions
        self.memory = memory
        self._lock = asyncio.Lock()

    async def commit_completion(self, session: BridgeSession,
                                memory: MemoryRecord) -> None:
        async with self._lock:
            paths = (self._path(self.sessions), self._path(self.memory))
            snapshots = [(path.exists(), path.read_bytes() if path.exists() else b"")
                         for path in paths]
            try:
                await self.sessions.upsert(session)
                await self.memory.append(memory)
            except BaseException:
                for path, (existed, content) in zip(paths, snapshots, strict=True):
                    if existed:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                    elif path.exists():
                        path.unlink()
                raise

    @staticmethod
    def _path(repository: object) -> Path:
        path = getattr(repository, "path", None)
        if not isinstance(path, Path):
            raise TypeError("FileUnitOfWork requires file-backed repositories")
        return path
