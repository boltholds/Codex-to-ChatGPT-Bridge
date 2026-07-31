from __future__ import annotations

import shlex
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SandboxMode = Literal["read-only", "workspace-write"]
ApprovalPolicy = Literal["untrusted", "on-request", "never"]
Transport = Literal["stdio", "streamable-http"]


class Settings(BaseSettings):
    """Runtime settings loaded from BRIDGE_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="BRIDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    codex_command: str = "codex"
    codex_args: str = "mcp-server"
    codex_timeout_seconds: int = Field(default=21_600, ge=60, le=86_400)
    allowed_roots: tuple[Path, ...] = Field(default_factory=lambda: (Path.cwd(),))
    memory_path: Path = Path(".bridge/memory.jsonl")
    sessions_path: Path = Path(".bridge/sessions.json")
    transport: Transport = "stdio"
    default_sandbox: SandboxMode = "workspace-write"
    default_approval_policy: ApprovalPolicy = "never"
    max_memory_items: int = Field(default=12, ge=1, le=50)
    max_memory_context_chars: int = Field(default=12_000, ge=1_000, le=200_000)
    max_codex_response_chars: int = Field(default=12_000, ge=1_000, le=20_000)
    max_event_text_chars: int = Field(default=2_000, ge=256, le=20_000)
    max_session_events: int = Field(default=50, ge=1, le=500)
    max_session_turns: int = Field(default=20, ge=1, le=200)

    @field_validator("allowed_roots", mode="after")
    @classmethod
    def normalize_allowed_roots(cls, roots: tuple[Path, ...]) -> tuple[Path, ...]:
        if not roots:
            raise ValueError("At least one allowed root is required")
        return tuple(root.expanduser().resolve() for root in roots)

    @property
    def codex_argv(self) -> list[str]:
        return shlex.split(self.codex_args)
