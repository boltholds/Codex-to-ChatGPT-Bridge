from types import SimpleNamespace

import pytest

from codex_chatgpt_bridge.models import MemoryHit, MemoryRecord
from codex_chatgpt_bridge.server import memory_search


@pytest.mark.asyncio
async def test_memory_search_facade_delegates_to_application_service() -> None:
    record = MemoryRecord(project="p", kind="fact", content="value", source="user")

    class Service:
        async def search_memory(self, **kwargs: object) -> list[MemoryHit]:
            assert kwargs == {
                "project": "p",
                "query": "needle",
                "limit": 50,
                "kind": None,
                "verified_only": True,
            }
            return [MemoryHit(record=record, score=0.75)]

    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(service=Service())
        )
    )
    result = await memory_search(
        project="p", ctx=ctx, query="needle", limit=100, verified_only=True
    )

    assert result[0]["score"] == 0.75
    assert result[0]["content"] == "value"
