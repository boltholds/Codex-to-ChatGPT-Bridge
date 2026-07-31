from __future__ import annotations

from ..models import BridgeSession, SessionStatus


def transition(session: BridgeSession, target: SessionStatus) -> BridgeSession:
    allowed = {"active": {"completed", "failed"}, "completed": set(), "failed": set()}
    if target not in allowed[session.status]:
        raise ValueError(
            f"Illegal session transition for {session.session_id}: {session.status} -> {target}"
        )
    session.status = target
    return session
