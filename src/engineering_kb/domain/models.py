"""Infrastructure-independent domain value objects."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from engineering_kb.domain.enums import (
    ContentType,
    DistanceMetric,
    SourceType,
    SourceVersionStatus,
    SyncStatus,
    SyncTrigger,
)
from engineering_kb.domain.identifiers import ChunkId, DocumentId, SourceId


@dataclass(frozen=True, slots=True)
class Source:
    id: SourceId
    source_type: SourceType
    name: str
    enabled: bool
    trust_level: int
    configuration: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_successful_sync_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class SourceVersion:
    id: str
    source_id: SourceId
    version_identifier: str
    status: SourceVersionStatus
    discovered_at: datetime
    content_hash: str | None = None
    revision: str | None = None
    indexed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Document:
    id: DocumentId
    source_version_id: str
    logical_path: str
    title: str
    content_hash: str
    enabled: bool = True
    language: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncRun:
    id: str
    started_at: datetime
    trigger: SyncTrigger
    status: SyncStatus
    finished_at: datetime | None = None
    sources_processed: int = 0
    documents_added: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    error_summary: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    provider: str
    model: str
    revision: str | None
    dimension: int | None
    normalize: bool
    query_prefix: str
    document_prefix: str
    distance_metric: DistanceMetric
    max_sequence_length: int
    precision: str
    pooling: str
    library_version: str | None = None


@dataclass(frozen=True, slots=True)
class RerankingProfile:
    provider: str
    model: str
    revision: str | None
    max_sequence_length: int
    precision: str


@dataclass(frozen=True, slots=True)
class RerankDocument:
    id: ChunkId
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RerankResult:
    document_id: ChunkId
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class ModelRuntimeInfo:
    device: str
    precision: str
    batch_size: int
    cpu_fallback_used: bool = False
    parameter_count: int | None = None
    estimated_model_bytes: int | None = None
    allocated_device_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    id: ChunkId
    document_id: DocumentId
    source_id: SourceId
    source_type: SourceType
    stable_key: str
    ordinal: int
    title: str
    content: str
    content_type: ContentType
    content_hash: str
    token_count: int
    trust_level: int
    document_version: str
    embedding_profile: str
    heading_path: tuple[str, ...] = ()
    language: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    indexed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: ChunkId
    stable_key: str
    source_id: SourceId
    title: str
    excerpt: str
    score: float
    source_type: SourceType
    content_type: ContentType
    trust_level: int
    version: str
    location: dict[str, Any] = field(default_factory=dict)
    document_id: DocumentId | None = None
    language: str | None = None
    token_count: int = 0
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SearchFilters:
    source_ids: tuple[str, ...] = ()
    source_types: tuple[SourceType, ...] = ()
    languages: tuple[str, ...] = ()
    content_types: tuple[ContentType, ...] = ()
    minimum_trust_level: int = 0
    path_prefixes: tuple[str, ...] = ()
