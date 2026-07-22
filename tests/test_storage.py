from pathlib import Path

import pytest

from codex_chatgpt_bridge.models import MemoryRecord
from codex_chatgpt_bridge.storage import MemoryStore


@pytest.mark.asyncio
async def test_memory_search_prefers_matching_verified_record(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.jsonl")
    await store.append(
        MemoryRecord(
            project="Gefest CAD",
            kind="decision",
            content="Rust solver is the source of truth for constraints.",
            source="user",
            verified=True,
            tags=["solver", "architecture"],
        )
    )
    await store.append(
        MemoryRecord(
            project="Gefest CAD",
            kind="note",
            content="The frontend has a graphite visual theme.",
            source="codex",
            confidence=0.4,
        )
    )

    hits = await store.search(
        project="Gefest CAD",
        query="solver constraints architecture",
        limit=2,
    )

    assert len(hits) == 2
    assert hits[0].record.kind == "decision"
    assert hits[0].record.verified is True
    assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_memory_isolated_by_project(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.jsonl")
    await store.append(
        MemoryRecord(
            project="A",
            kind="fact",
            content="alpha",
            source="user",
        )
    )
    await store.append(
        MemoryRecord(
            project="B",
            kind="fact",
            content="beta",
            source="user",
        )
    )

    hits = await store.search(project="A")
    assert [hit.record.content for hit in hits] == ["alpha"]
