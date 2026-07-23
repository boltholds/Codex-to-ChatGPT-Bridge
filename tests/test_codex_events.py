import mcp.types as types

from codex_chatgpt_bridge.codex_events import (
    CodexEventNotification,
    CodexServerNotification,
    normalize_codex_event,
)


def test_accepts_standard_mcp_notification() -> None:
    notification = CodexServerNotification.model_validate(
        {
            "method": "notifications/tools/list_changed",
            "params": {},
        }
    )

    assert isinstance(notification.root, types.ToolListChangedNotification)


def test_accepts_and_normalizes_codex_event() -> None:
    notification = CodexServerNotification.model_validate(
        {
            "method": "codex/event",
            "params": {
                "_meta": {"threadId": "thread-1"},
                "id": "2",
                "msg": {
                    "type": "exec_command_end",
                    "turn_id": "turn-1",
                    "command": ["pwsh", "-Command", "echo sk-proj-SECRETSECRET"],
                    "cwd": "C:/repo",
                    "exit_code": 0,
                    "duration": {"secs": 1, "nanos": 500_000_000},
                    "stdout": "done",
                    "stderr": "",
                },
            },
        }
    )

    assert isinstance(notification.root, CodexEventNotification)
    event = normalize_codex_event(notification.root, max_text_chars=100)

    assert event.event_type == "exec_command_end"
    assert event.thread_id == "thread-1"
    assert event.turn_id == "turn-1"
    assert event.details["exit_code"] == 0
    assert event.details["duration_ms"] == 1500
    assert "SECRETSECRET" not in str(event.details["command"])
    assert event.details["stdout_chars"] == 4


def test_turn_diff_keeps_file_names_not_full_diff() -> None:
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
"""
    notification = CodexEventNotification.model_validate(
        {
            "method": "codex/event",
            "params": {
                "msg": {"type": "turn_diff", "unified_diff": diff},
            },
        }
    )

    event = normalize_codex_event(notification, max_text_chars=100)

    assert event.details["changed_files"] == ["src/a.py", "tests/test_a.py"]
    assert event.details["diff_chars"] == len(diff)
    assert "unified_diff" not in event.details


def test_token_count_extracts_usage_and_rate_limit() -> None:
    notification = CodexEventNotification.model_validate(
        {
            "method": "codex/event",
            "params": {
                "msg": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 80,
                            "output_tokens": 20,
                            "total_tokens": 120,
                        },
                        "model_context_window": 258_400,
                        "rate_limits": {"primary": {"used_percent": 84.0}},
                    },
                },
            },
        }
    )

    event = normalize_codex_event(notification, max_text_chars=100)

    assert event.details["total_token_usage"] == {
        "input_tokens": 100,
        "cached_input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    assert event.details["model_context_window"] == 258_400
    assert event.details["rate_limit_used_percent"] == 84.0
