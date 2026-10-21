"""Incremental, snapshot-based PDF synchronization."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from engineering_kb.domain.enums import ContentType, SourceType
from engineering_kb.domain.identifiers import ChunkId, DocumentId, SourceId, source_id
from engineering_kb.domain.interfaces import EmbeddingProvider
from engineering_kb.domain.models import Chunk, Document, EmbeddingProfile, Source
from engineering_kb.ingestion.base import ExtractedDocument
from engineering_kb.ingestion.pdf import PdfExtractor
from engineering_kb.processing.chunking import TextChunker
from engineering_kb.settings import PdfDirectorySourceConfig


@dataclass(frozen=True, slots=True)
class StoredDocument:
    document: Document
    chunks: tuple[Chunk, ...]


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    version_identifier: str
    content_hash: str
    documents: dict[str, StoredDocument]


@dataclass(frozen=True, slots=True)
class SyncSummary:
    source_id: str
    version_identifier: str
    documents_added: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    chunks_embedded: int = 0
    unchanged: bool = False


class SnapshotMetadataStore(Protocol):
    async def latest_snapshot(
        self, source_id: SourceId, embedding_profile: str
    ) -> SourceSnapshot | None: ...

    async def activate_snapshot(
        self,
        source: Source,
        version_identifier: str,
        content_hash: str,
        documents: Sequence[StoredDocument],
        summary: SyncSummary,
    ) -> None: ...

    async def record_unchanged(self, source: Source, summary: SyncSummary) -> None: ...

    async def record_failure(self, source: Source, error: str) -> None: ...


class SnapshotIndex(Protocol):
    async def delete_source_version(
        self,
        profile: EmbeddingProfile,
        source_id: SourceId,
        version: str,
    ) -> None: ...

    async def upsert(
        self,
        profile: EmbeddingProfile,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None: ...

    async def clone(
        self,
        profile: EmbeddingProfile,
        old_chunks: Sequence[Chunk],
        new_chunks: Sequence[Chunk],
    ) -> None: ...

    async def delete(self, profile: EmbeddingProfile, point_ids: Sequence[str]) -> None: ...


class PdfSyncService:
    def __init__(
        self,
        *,
        metadata: SnapshotMetadataStore,
        index: SnapshotIndex,
        embeddings: EmbeddingProvider,
        extractor: PdfExtractor,
        chunker: TextChunker,
        embedding_profile_name: str,
    ) -> None:
        self._metadata = metadata
        self._index = index
        self._embeddings = embeddings
        self._extractor = extractor
        self._chunker = chunker
        self._embedding_profile_name = embedding_profile_name

    async def record_failure(
        self, configuration: PdfDirectorySourceConfig, error: Exception
    ) -> None:
        message = f"{type(error).__name__}: {error}"
        await self._metadata.record_failure(_source(configuration), message[:4000])

    async def synchronize(
        self, configuration: PdfDirectorySourceConfig, *, force: bool = False
    ) -> SyncSummary:
        identifier = source_id(configuration.id)
        root = configuration.path.resolve()
        paths = self._extractor.discover(configuration)
        hashes = {
            path.relative_to(root).as_posix(): self._extractor.file_hash(path) for path in paths
        }
        content_version = _source_version(hashes)
        current = await self._metadata.latest_snapshot(identifier, self._embedding_profile_name)
        source = _source(configuration)
        if current is not None and current.content_hash == content_version and not force:
            summary = SyncSummary(configuration.id, current.version_identifier, unchanged=True)
            await self._metadata.record_unchanged(source, summary)
            return summary

        version = content_version
        if current is not None and current.content_hash == content_version:
            version = f"{content_version}:force:{uuid4()}"

        old_documents = current.documents if current else {}
        new_documents: list[StoredDocument] = []
        cloned_pairs: list[tuple[tuple[Chunk, ...], tuple[Chunk, ...]]] = []
        chunks_to_embed: list[Chunk] = []
        added = updated = 0

        for path in paths:
            logical_path = path.relative_to(root).as_posix()
            previous = old_documents.get(logical_path)
            if (
                previous is not None
                and previous.document.content_hash == hashes[logical_path]
                and not force
            ):
                cloned = _clone_document(previous, version, source.id)
                new_documents.append(cloned)
                cloned_pairs.append((previous.chunks, cloned.chunks))
                continue
            extracted = self._extractor.extract(path, root=root)
            prepared = _prepare_document(
                extracted,
                source=source,
                version=version,
                profile_name=self._embedding_profile_name,
                chunker=self._chunker,
            )
            new_documents.append(prepared)
            chunks_to_embed.extend(prepared.chunks)
            if previous is None:
                added += 1
            else:
                updated += 1

        deleted = len(set(old_documents) - set(hashes))
        vectors = await self._embeddings.embed_documents(
            [chunk.content for chunk in chunks_to_embed]
        )
        profile = self._embeddings.profile
        await self._index.delete_source_version(profile, source.id, version)
        await self._index.upsert(profile, chunks_to_embed, vectors)
        for old_chunks, new_chunks in cloned_pairs:
            await self._index.clone(profile, old_chunks, new_chunks)

        summary = SyncSummary(
            source_id=configuration.id,
            version_identifier=version,
            documents_added=added,
            documents_updated=updated,
            documents_deleted=deleted,
            chunks_embedded=len(chunks_to_embed),
        )
        await self._metadata.activate_snapshot(
            source, version, content_version, new_documents, summary
        )
        if current is not None:
            old_ids = [
                str(chunk.id) for item in current.documents.values() for chunk in item.chunks
            ]
            await self._index.delete(profile, old_ids)
        return summary


def _source(configuration: PdfDirectorySourceConfig) -> Source:
    return Source(
        id=source_id(configuration.id),
        source_type=SourceType.PDF_DIRECTORY,
        name=configuration.name or configuration.id,
        enabled=configuration.enabled,
        trust_level=configuration.trust_level,
        configuration=configuration.model_dump(mode="json"),
    )


def _source_version(hashes: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, content_hash in sorted(hashes.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content_hash.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _prepare_document(
    extracted: ExtractedDocument,
    *,
    source: Source,
    version: str,
    profile_name: str,
    chunker: TextChunker,
) -> StoredDocument:
    document_id = DocumentId(
        str(uuid5(NAMESPACE_URL, f"pdf-document:{source.id}:{version}:{extracted.logical_path}"))
    )
    document = Document(
        id=document_id,
        source_version_id=version,
        logical_path=extracted.logical_path,
        title=extracted.title,
        language=extracted.language,
        mime_type=extracted.mime_type,
        content_hash=extracted.content_hash,
        metadata=dict(extracted.metadata),
    )
    chunks: list[Chunk] = []
    for item in chunker.chunk(extracted):
        stable_key = (
            f"pdf:{source.id}:{extracted.content_hash}:"
            f"page-{item.page_number}:chunk-{item.page_chunk_number}"
        )
        chunk_id = ChunkId(str(uuid5(NAMESPACE_URL, f"{version}:{stable_key}:{profile_name}")))
        content_hash = hashlib.sha256(item.text.encode()).hexdigest()
        chunks.append(
            Chunk(
                id=chunk_id,
                document_id=document_id,
                source_id=source.id,
                source_type=source.source_type,
                stable_key=stable_key,
                ordinal=item.ordinal,
                title=extracted.title,
                content=item.text,
                content_type=ContentType.UNKNOWN,
                content_hash=content_hash,
                token_count=item.token_count,
                trust_level=source.trust_level,
                document_version=version,
                embedding_profile=profile_name,
                heading_path=item.heading_path,
                language=extracted.language,
                location={"path": extracted.logical_path, "page": item.page_number},
            )
        )
    return StoredDocument(document=document, chunks=tuple(chunks))


def _clone_document(
    previous: StoredDocument, version: str, source_identifier: SourceId
) -> StoredDocument:
    document_id = DocumentId(
        str(
            uuid5(
                NAMESPACE_URL,
                f"pdf-document:{source_identifier}:{version}:{previous.document.logical_path}",
            )
        )
    )
    document = replace(previous.document, id=document_id, source_version_id=version)
    chunks = tuple(
        replace(
            chunk,
            id=ChunkId(str(uuid5(NAMESPACE_URL, f"{version}:{chunk.stable_key}"))),
            document_id=document_id,
            document_version=version,
            indexed_at=datetime.now(UTC),
        )
        for chunk in previous.chunks
    )
    return StoredDocument(document=document, chunks=chunks)


class SyncService:
    """Compatibility name retained for callers; use PdfSyncService in milestone 2."""

    pass
