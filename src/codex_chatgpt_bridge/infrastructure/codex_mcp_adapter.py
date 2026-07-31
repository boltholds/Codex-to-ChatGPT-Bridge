from ..codex_client import CodexMCPClient as LegacyCodexMCPClient


class CodexMCPClient(LegacyCodexMCPClient):
    """Infrastructure adapter for the official ``codex mcp-server``."""

__all__ = ["CodexMCPClient"]
