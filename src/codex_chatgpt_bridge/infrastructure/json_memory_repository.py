from ..storage import MemoryStore


class JsonMemoryRepository(MemoryStore):
    """Append-only memory repository using the legacy JSONL representation."""

__all__ = ["JsonMemoryRepository"]
