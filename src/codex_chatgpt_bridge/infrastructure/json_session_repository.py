from ..storage import SessionStore


class JsonSessionRepository(SessionStore):
    """File-backed session repository using the legacy JSON representation."""

__all__ = ["JsonSessionRepository"]
