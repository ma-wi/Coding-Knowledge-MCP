"""Shared hybrid retrieval pipeline for CLI and future MCP adapters."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from engineering_kb.domain.enums import ContentType, SourceType
from engineering_kb.domain.interfaces import EmbeddingProvider, RerankingProvider
from engineering_kb.domain.models import EmbeddingProfile, RerankDocument, SearchFilters, SearchHit
from engineering_kb.retrieval.budget import apply_token_budget
from engineering_kb.retrieval.diversification import diversify
from engineering_kb.retrieval.fusion import reciprocal_rank_fusion


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    profile: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    top_k: int | None = None
    token_budget: int | None = None
    task_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    total_seconds: float
    embedding_seconds: float
    reranking_seconds: float


@dataclass(frozen=True, slots=True)
class SearchResponse:
    hits: tuple[SearchHit, ...]
    diagnostics: SearchDiagnostics


class DenseSearchIndex(Protocol):
    async def search(
        self,
        profile: EmbeddingProfile,
        vector: list[float],
        *,
        limit: int,
        active_versions: dict[str, str],
        filters: SearchFilters,
    ) -> tuple[SearchHit, ...]: ...


class SparseSearchIndex(Protocol):
    async def search(
        self,
        query: str,
        *,
        embedding_profile: str,
        limit: int,
        active_versions: dict[str, str],
        filters: SearchFilters,
    ) -> tuple[SearchHit, ...]: ...


class ActiveVersionStore(Protocol):
    async def active_versions(
        self, *, source_ids: tuple[str, ...], embedding_profile: str
    ) -> dict[str, str]: ...


class SearchService:
    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider,
        index: DenseSearchIndex,
        versions: ActiveVersionStore,
        embedding_profile_name: str,
        default_results: int,
        sparse_index: SparseSearchIndex | None = None,
        dense_candidates: int = 30,
        sparse_candidates: int = 30,
        fusion_candidates: int = 40,
        rerank_candidates: int = 20,
        maximum_results: int = 20,
        minimum_score: float = 0.0,
        rrf_k: int = 60,
        diversification_enabled: bool = True,
        max_results_per_document: int = 2,
        max_results_per_source_version: int = 3,
        near_duplicate_threshold: float = 0.9,
        max_excerpt_tokens_per_result: int = 600,
        max_total_tokens: int = 4500,
        reranker: RerankingProvider | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._index = index
        self._versions = versions
        self._sparse_index = sparse_index
        self._embedding_profile_name = embedding_profile_name
        self._default_results = default_results
        self._dense_candidates = dense_candidates
        self._sparse_candidates = sparse_candidates
        self._fusion_candidates = fusion_candidates
        self._rerank_candidates = rerank_candidates
        self._maximum_results = maximum_results
        self._minimum_score = minimum_score
        self._rrf_k = rrf_k
        self._diversification_enabled = diversification_enabled
        self._max_results_per_document = max_results_per_document
        self._max_results_per_source_version = max_results_per_source_version
        self._near_duplicate_threshold = near_duplicate_threshold
        self._max_excerpt_tokens_per_result = max_excerpt_tokens_per_result
        self._max_total_tokens = max_total_tokens
        self._reranker = reranker

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        return (await self.search_with_diagnostics(request)).hits

    async def search_with_diagnostics(self, request: SearchRequest) -> SearchResponse:
        started = time.perf_counter()
        query = _query_text(request.query, request.task_context)
        if not query:
            raise ValueError("query must not be empty")
        limit = self._default_results if request.top_k is None else request.top_k
        if limit < 1 or limit > self._maximum_results:
            raise ValueError(f"top_k must be between 1 and {self._maximum_results}")
        filters = _parse_filters(request.filters)
        active_versions = await self._versions.active_versions(
            source_ids=filters.source_ids,
            embedding_profile=self._embedding_profile_name,
        )
        if not active_versions:
            return SearchResponse(
                hits=(),
                diagnostics=SearchDiagnostics(
                    total_seconds=time.perf_counter() - started,
                    embedding_seconds=0.0,
                    reranking_seconds=0.0,
                ),
            )
        embedding_started = time.perf_counter()
        vector = await self._embeddings.embed_query(query)
        embedding_seconds = time.perf_counter() - embedding_started
        dense_task = self._index.search(
            self._embeddings.profile,
            vector,
            limit=self._dense_candidates,
            active_versions=active_versions,
            filters=filters,
        )
        if self._sparse_index is None:
            dense = await dense_task
            sparse: tuple[SearchHit, ...] = ()
        else:
            dense, sparse = await asyncio.gather(
                dense_task,
                self._sparse_index.search(
                    query,
                    embedding_profile=self._embedding_profile_name,
                    limit=self._sparse_candidates,
                    active_versions=active_versions,
                    filters=filters,
                ),
            )
        fused = reciprocal_rank_fusion(
            dense,
            sparse,
            rrf_k=self._rrf_k,
            limit=self._fusion_candidates,
        )
        candidates = tuple(hit for hit in fused if hit.score >= self._minimum_score)[
            : self._rerank_candidates
        ]
        reranking_seconds = 0.0
        if self._reranker is not None and candidates:
            reranking_started = time.perf_counter()
            candidates = await _rerank(self._reranker, query, candidates)
            reranking_seconds = time.perf_counter() - reranking_started
        if self._diversification_enabled:
            candidates = diversify(
                candidates,
                limit=limit,
                max_per_document=self._max_results_per_document,
                max_per_source_version=self._max_results_per_source_version,
                near_duplicate_threshold=self._near_duplicate_threshold,
            )
        requested_budget = (
            self._max_total_tokens if request.token_budget is None else request.token_budget
        )
        if requested_budget < 1:
            raise ValueError("token_budget must be positive")
        hits = apply_token_budget(
            candidates,
            limit=limit,
            per_result=self._max_excerpt_tokens_per_result,
            total=min(requested_budget, self._max_total_tokens),
        )
        return SearchResponse(
            hits=hits,
            diagnostics=SearchDiagnostics(
                total_seconds=time.perf_counter() - started,
                embedding_seconds=embedding_seconds,
                reranking_seconds=reranking_seconds,
            ),
        )


def _parse_filters(values: dict[str, Any]) -> SearchFilters:
    allowed = {
        "source_ids",
        "source_types",
        "languages",
        "content_types",
        "minimum_trust_level",
        "path_prefixes",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown search filters: {', '.join(sorted(unknown))}")
    source_types = tuple(SourceType(value) for value in _strings(values, "source_types"))
    content_types = tuple(ContentType(value) for value in _strings(values, "content_types"))
    trust = values.get("minimum_trust_level", 0)
    if isinstance(trust, bool) or not isinstance(trust, int) or not 0 <= trust <= 100:
        raise ValueError("minimum_trust_level must be an integer between 0 and 100")
    return SearchFilters(
        source_ids=_strings(values, "source_ids"),
        source_types=source_types,
        languages=tuple(value.lower() for value in _strings(values, "languages")),
        content_types=content_types,
        minimum_trust_level=trust,
        path_prefixes=_strings(values, "path_prefixes"),
    )


def _strings(values: dict[str, Any], name: str) -> tuple[str, ...]:
    raw = values.get(name, ())
    if not isinstance(raw, (list, tuple)) or any(
        not isinstance(value, str) or not value for value in raw
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(raw)


async def _rerank(
    provider: RerankingProvider, query: str, candidates: tuple[SearchHit, ...]
) -> tuple[SearchHit, ...]:
    by_id = {str(hit.chunk_id): hit for hit in candidates}
    documents = [
        RerankDocument(
            id=hit.chunk_id,
            text=hit.excerpt,
            metadata={"stable_key": hit.stable_key, "source_id": str(hit.source_id)},
        )
        for hit in candidates
    ]
    results = await provider.rerank(query, documents, top_k=len(documents))
    if len(results) != len(documents):
        raise RuntimeError("reranker returned an invalid result count")
    output: list[SearchHit] = []
    seen: set[str] = set()
    for result in sorted(results, key=lambda item: item.rank):
        identifier = str(result.document_id)
        hit = by_id.get(identifier)
        if hit is None:
            raise RuntimeError("reranker returned an unknown chunk ID")
        if identifier in seen:
            raise RuntimeError("reranker returned a duplicate chunk ID")
        seen.add(identifier)
        output.append(replace(hit, score=result.score, rerank_score=result.score))
    return tuple(output)


def _query_text(query: str, context: dict[str, Any]) -> str:
    normalized = " ".join(query.split())
    if not normalized:
        return ""
    additions: list[str] = []
    for name in ("objective", "programming_language", "project_name"):
        value = context.get(name)
        if isinstance(value, str) and value.strip():
            additions.append(" ".join(value.split())[:500])
    for name in ("frameworks", "current_files", "symbols"):
        values = context.get(name)
        if isinstance(values, (list, tuple)):
            additions.extend(
                " ".join(value.split())[:200]
                for value in values[:20]
                if isinstance(value, str) and value.strip()
            )
    return " ".join([normalized, *additions])
