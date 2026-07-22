from __future__ import annotations

from pathlib import Path
from uuid import UUID

from .codex_client import CodexClient
from .config import ApprovalPolicy, SandboxMode, Settings
from .models import (
    BridgeSession,
    MemoryKind,
    MemoryRecord,
    MemorySource,
    SessionStatus,
)
from .storage import MemoryStore, SessionStore

_DEVELOPER_INSTRUCTIONS = """\
You are a coding agent working under a coordinator.
Work only inside the provided working directory.
Do not commit, push, create pull requests, or access secrets unless the current task
explicitly asks.
Inspect existing code before editing, make focused changes, and run relevant checks.
In the final response report: summary, changed files, commands run, test results,
risks, and remaining work.
"""


class BridgeService:
    def __init__(
        self,
        *,
        settings: Settings,
        codex: CodexClient,
        memory: MemoryStore,
        sessions: SessionStore,
    ) -> None:
        self.settings = settings
        self.codex = codex
        self.memory = memory
        self.sessions = sessions

    async def start_task(
        self,
        *,
        project: str,
        objective: str,
        cwd: str,
        repository: str | None = None,
        task_id: str | None = None,
        branch: str | None = None,
        sandbox: SandboxMode | None = None,
        approval_policy: ApprovalPolicy | None = None,
        model: str | None = None,
        memory_query: str | None = None,
    ) -> BridgeSession:
        resolved_cwd = self._resolve_cwd(cwd)
        hits = await self.memory.search(
            project=project,
            query=memory_query or objective,
            limit=self.settings.max_memory_items,
        )
        prompt = self._build_start_prompt(
            project=project,
            objective=objective,
            repository=repository,
            task_id=task_id,
            branch=branch,
            memories=[hit.record for hit in hits],
        )
        turn = await self.codex.start_turn(
            prompt=prompt,
            cwd=str(resolved_cwd),
            sandbox=sandbox or self.settings.default_sandbox,
            approval_policy=approval_policy or self.settings.default_approval_policy,
            developer_instructions=_DEVELOPER_INSTRUCTIONS,
            model=model,
        )
        session = BridgeSession(
            thread_id=turn.thread_id,
            project=project,
            cwd=str(resolved_cwd),
            objective=objective,
            repository=repository,
            task_id=task_id,
            branch=branch,
            memory_ids=[hit.record.id for hit in hits],
            last_response=turn.content,
        )
        await self.sessions.upsert(session)
        await self.memory.append(
            MemoryRecord(
                project=project,
                kind="episode",
                content=(
                    f"Codex session {session.session_id} started for objective: {objective}. "
                    f"Initial response: {turn.content}"
                ),
                source="codex",
                repository=repository,
                task_id=task_id,
                branch=branch,
                confidence=0.5,
                verified=False,
                tags=["codex-session", "started"],
            )
        )
        return session

    async def continue_task(
        self,
        *,
        session_id: UUID,
        instruction: str,
        include_memory: bool = True,
    ) -> BridgeSession:
        session = await self._require_session(session_id)
        if session.status != "active":
            raise ValueError(f"Session {session_id} is {session.status}, not active")

        memory_context = ""
        if include_memory:
            hits = await self.memory.search(
                project=session.project,
                query=instruction,
                limit=min(6, self.settings.max_memory_items),
            )
            if hits:
                memory_context = "\n\nRelevant durable context:\n" + self._format_memories(
                    [hit.record for hit in hits]
                )

        turn = await self.codex.continue_turn(
            thread_id=session.thread_id,
            prompt=instruction + memory_context,
        )
        session.thread_id = turn.thread_id
        session.last_response = turn.content
        await self.sessions.upsert(session)
        await self.memory.append(
            MemoryRecord(
                project=session.project,
                kind="episode",
                content=(
                    f"Codex session {session.session_id} continued. "
                    f"Instruction: {instruction}\nResponse: {turn.content}"
                ),
                source="codex",
                repository=session.repository,
                task_id=session.task_id,
                branch=session.branch,
                confidence=0.5,
                verified=False,
                tags=["codex-session", "turn"],
            )
        )
        return session

    async def complete_task(
        self,
        *,
        session_id: UUID,
        summary: str,
        commit_sha: str | None = None,
        verification: str | None = None,
    ) -> BridgeSession:
        session = await self._require_session(session_id)
        session.status = "completed"
        await self.sessions.upsert(session)

        content = summary
        if verification:
            content += f"\nVerification: {verification}"
        await self.memory.append(
            MemoryRecord(
                project=session.project,
                kind="result",
                content=content,
                source="chatgpt",
                repository=session.repository,
                task_id=session.task_id,
                branch=session.branch,
                commit_sha=commit_sha,
                confidence=1.0,
                verified=True,
                tags=["codex-session", "completed"],
            )
        )
        return session

    async def record_memory(
        self,
        *,
        project: str,
        kind: MemoryKind,
        content: str,
        source: MemorySource = "chatgpt",
        tags: list[str] | None = None,
        repository: str | None = None,
        task_id: str | None = None,
        branch: str | None = None,
        commit_sha: str | None = None,
        confidence: float = 1.0,
        verified: bool = False,
        supersedes: UUID | None = None,
    ) -> MemoryRecord:
        return await self.memory.append(
            MemoryRecord(
                project=project,
                kind=kind,
                content=content,
                source=source,
                tags=tags or [],
                repository=repository,
                task_id=task_id,
                branch=branch,
                commit_sha=commit_sha,
                confidence=confidence,
                verified=verified,
                supersedes=supersedes,
            )
        )

    async def get_session(self, session_id: UUID) -> BridgeSession:
        return await self._require_session(session_id)

    async def list_sessions(
        self,
        *,
        project: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 20,
    ) -> list[BridgeSession]:
        return await self.sessions.list(project=project, status=status, limit=limit)

    async def _require_session(self, session_id: UUID) -> BridgeSession:
        session = await self.sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown bridge session: {session_id}")
        return session

    def _resolve_cwd(self, cwd: str) -> Path:
        resolved = Path(cwd).expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"Working directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Working directory is not a directory: {resolved}")

        allowed = any(
            resolved == root or root in resolved.parents
            for root in self.settings.allowed_roots
        )
        if not allowed:
            roots = ", ".join(str(root) for root in self.settings.allowed_roots)
            raise PermissionError(
                f"Working directory {resolved} is outside allowed roots: {roots}"
            )
        return resolved

    @staticmethod
    def _build_start_prompt(
        *,
        project: str,
        objective: str,
        repository: str | None,
        task_id: str | None,
        branch: str | None,
        memories: list[MemoryRecord],
    ) -> str:
        metadata = [
            f"Project: {project}",
            f"Objective: {objective}",
        ]
        if repository:
            metadata.append(f"Repository: {repository}")
        if task_id:
            metadata.append(f"Task: {task_id}")
        if branch:
            metadata.append(f"Expected branch: {branch}")

        context = BridgeService._format_memories(memories)
        return (
            "Execute the following coordinated development task.\n\n"
            + "\n".join(metadata)
            + "\n\nDurable project context:\n"
            + (context or "(no matching records)")
            + "\n\nBegin by inspecting the repository and current git state. "
            "Do not commit or push unless the objective explicitly requests it."
        )

    @staticmethod
    def _format_memories(memories: list[MemoryRecord]) -> str:
        lines: list[str] = []
        for index, record in enumerate(memories, start=1):
            state = "verified" if record.verified else "unverified"
            lines.append(
                f"{index}. [{record.kind}; {state}; confidence={record.confidence:.2f}] "
                f"{record.content}"
            )
        return "\n".join(lines)
