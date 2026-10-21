"""Read-only knowledge-base status aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class StatusCounts:
    last_successful_sync: datetime | None
    last_failed_sync: datetime | None
    active_sources: int
    failed_sources: int
    documents: int
    chunks: int


class StatusStore(Protocol):
    async def status_counts(self, *, embedding_profile: str) -> StatusCounts: ...


@dataclass(frozen=True, slots=True)
class KnowledgeBaseStatus:
    last_successful_sync: datetime | None
    last_failed_sync: datetime | None
    active_sources: int
    failed_sources: int
    documents: int
    chunks: int
    active_embedding_profile: str
    active_reranker_profile: str
    qdrant_available: bool
    gpu_status: dict[str, Any]
    index_version: str | None


class StatusService:
    def __init__(self, store: StatusStore) -> None:
        self._store = store

    async def get(
        self,
        *,
        embedding_profile: str,
        reranker_profile: str,
        qdrant_available: bool,
        gpu_status: dict[str, Any],
        index_version: str | None,
    ) -> KnowledgeBaseStatus:
        counts = await self._store.status_counts(embedding_profile=embedding_profile)
        return KnowledgeBaseStatus(
            **asdict(counts),
            active_embedding_profile=embedding_profile,
            active_reranker_profile=reranker_profile,
            qdrant_available=qdrant_available,
            gpu_status=gpu_status,
            index_version=index_version,
        )
