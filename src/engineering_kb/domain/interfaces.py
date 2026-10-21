"""Ports implemented by infrastructure adapters in later milestones."""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from engineering_kb.domain.identifiers import ChunkId, SourceId
from engineering_kb.domain.models import (
    Chunk,
    EmbeddingProfile,
    RerankDocument,
    RerankingProfile,
    RerankResult,
    Source,
)


class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class RerankingProvider(Protocol):
    @property
    def profile(self) -> RerankingProfile: ...

    async def rerank(
        self, query: str, documents: Sequence[RerankDocument], *, top_k: int
    ) -> list[RerankResult]: ...


class ChunkIndex(Protocol):
    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def deactivate(self, chunk_ids: Sequence[ChunkId]) -> None: ...


class SourceReader(Protocol):
    async def version_identifier(self) -> str: ...

    def read(self) -> AsyncIterator[bytes]: ...


class SourceRepository(Protocol):
    async def get(self, source_id: SourceId) -> Source | None: ...

    async def list_enabled(self) -> Sequence[Source]: ...
