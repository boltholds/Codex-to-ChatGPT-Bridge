from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeAlias

import mcp.types as types
from mcp import ClientSession
from pydantic import BaseModel, ConfigDict, Field, RootModel

from .models import CodexEvent

_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(?:authorization|api[_-]?key|token)\s*[:=]\s*[^\s,;]+"),
)
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


class CodexEventParams(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
    msg: dict[str, Any] = Field(default_factory=dict)
    event_id: str | int | None = Field(default=None, alias="id")


class CodexEventNotification(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: Literal["codex/event"] = "codex/event"
    params: CodexEventParams


CodexServerNotificationType: TypeAlias = (
    types.ServerNotificationType | CodexEventNotification
)


class CodexServerNotification(RootModel[CodexServerNotificationType]):
    pass


CodexEventHandler = Callable[[CodexEventNotification], Awaitable[None]]


class CodexClientSession(ClientSession):
    """ClientSession variant that accepts Codex's `codex/event` extension."""

    def __init__(
        self,
        *args: Any,
        codex_event_handler: CodexEventHandler,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._codex_event_handler = codex_event_handler
        self._receive_notification_type = CodexServerNotification

    async def _received_notification(
        self,
        notification: CodexServerNotification,
    ) -> None:
        if isinstance(notification.root, CodexEventNotification):
            await self._codex_event_handler(notification.root)
            return
        await super()._received_notification(
            types.ServerNotification(root=notification.root)
        )

    async def _handle_incoming(self, incoming: Any) -> None:
        if isinstance(incoming, CodexServerNotification):
            if isinstance(incoming.root, CodexEventNotification):
                return
            incoming = types.ServerNotification(root=incoming.root)
        await super()._handle_incoming(incoming)


def normalize_codex_event(
    notification: CodexEventNotification,
    *,
    max_text_chars: int,
) -> CodexEvent:
    msg = notification.params.msg
    event_type = _as_text(msg.get("type"), fallback="unknown")
    meta = notification.params.meta
    thread_id = _first_text(meta.get("threadId"), msg.get("thread_id"))
    turn_id = _first_text(msg.get("turn_id"), meta.get("turnId"))
    status = _first_text(msg.get("status"), _nested(msg, "item", "status"))
    timestamp_ms = _first_int(
        msg.get("completed_at_ms"),
        msg.get("started_at_ms"),
        msg.get("timestamp_ms"),
    )

    details = _normalize_details(msg, event_type, max_text_chars=max_text_chars)
    return CodexEvent(
        event_type=event_type,
        thread_id=thread_id,
        turn_id=turn_id,
        status=status,
        timestamp_ms=timestamp_ms,
        details=details,
    )


def _normalize_details(
    msg: dict[str, Any],
    event_type: str,
    *,
    max_text_chars: int,
) -> dict[str, object]:
    details: dict[str, object] = {}
    item = msg.get("item") if isinstance(msg.get("item"), dict) else {}

    item_type = _first_text(item.get("type"), msg.get("item_type"))
    if item_type:
        details["item_type"] = item_type

    command = _first_value(msg.get("command"), item.get("command"))
    if command is not None:
        details["command"] = _safe_text(_command_text(command), max_text_chars)

    cwd = _first_text(msg.get("cwd"), item.get("cwd"))
    if cwd:
        details["cwd"] = _safe_text(cwd, max_text_chars)

    exit_code = _first_int(msg.get("exit_code"), item.get("exit_code"))
    if exit_code is not None:
        details["exit_code"] = exit_code

    duration_ms = _duration_ms(_first_value(msg.get("duration"), item.get("duration")))
    if duration_ms is not None:
        details["duration_ms"] = duration_ms

    stdout = _first_text(msg.get("stdout"), item.get("stdout"))
    stderr = _first_text(msg.get("stderr"), item.get("stderr"))
    if stdout is not None:
        details["stdout_chars"] = len(stdout)
        if stdout:
            details["stdout_preview"] = _safe_text(stdout, max_text_chars)
    if stderr is not None:
        details["stderr_chars"] = len(stderr)
        if stderr:
            details["stderr_preview"] = _safe_text(stderr, max_text_chars)

    if event_type == "turn_diff":
        diff = _as_text(msg.get("unified_diff"), fallback="")
        details["diff_chars"] = len(diff)
        details["changed_files"] = sorted(
            {right for _, right in _DIFF_FILE_RE.findall(diff)}
        )

    token_payload = _first_mapping(msg.get("info"), msg.get("token_usage"))
    if token_payload:
        total_usage = token_payload.get("total_token_usage")
        last_usage = token_payload.get("last_token_usage")
        if isinstance(total_usage, dict):
            details["total_token_usage"] = _numeric_mapping(total_usage)
        elif event_type == "raw_response_completed":
            details["last_token_usage"] = _numeric_mapping(token_payload)
        if isinstance(last_usage, dict):
            details["last_token_usage"] = _numeric_mapping(last_usage)
        context_window = token_payload.get("model_context_window")
        if isinstance(context_window, int):
            details["model_context_window"] = context_window
        rate_limits = token_payload.get("rate_limits")
        if isinstance(rate_limits, dict):
            primary = rate_limits.get("primary")
            if isinstance(primary, dict):
                used_percent = primary.get("used_percent")
                if isinstance(used_percent, int | float):
                    details["rate_limit_used_percent"] = float(used_percent)

    for key in ("name", "call_id", "response_id", "error"):
        value = msg.get(key)
        if isinstance(value, str) and value:
            details[key] = _safe_text(value, max_text_chars)

    if event_type == "raw_response_item":
        raw_item = msg.get("item")
        if isinstance(raw_item, dict):
            raw_type = raw_item.get("type")
            if isinstance(raw_type, str):
                details["raw_item_type"] = raw_type
            name = raw_item.get("name")
            if isinstance(name, str):
                details["name"] = name
            raw_input = raw_item.get("input")
            if isinstance(raw_input, str):
                details["input_preview"] = _safe_text(raw_input, max_text_chars)

    return details


def _safe_text(value: str, limit: int) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    if len(redacted) <= limit:
        return redacted
    if limit <= 1:
        return "…"[:limit]
    return redacted[: limit - 1].rstrip() + "…"


def _command_text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    return str(value)


def _duration_ms(value: object) -> int | None:
    if isinstance(value, dict):
        seconds = value.get("secs", 0)
        nanos = value.get("nanos", 0)
        if isinstance(seconds, int) and isinstance(nanos, int):
            return (seconds * 1000) + (nanos // 1_000_000)
    return None


def _numeric_mapping(value: dict[str, Any]) -> dict[str, int | float]:
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, int | float) and not isinstance(item, bool)
    }


def _nested(mapping: dict[str, Any], *path: str) -> object:
    current: object = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_mapping(*values: object) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _first_value(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return None


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str):
            return value
    return None


def _first_int(*values: object) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _as_text(value: object, *, fallback: str) -> str:
    return value if isinstance(value, str) else fallback
