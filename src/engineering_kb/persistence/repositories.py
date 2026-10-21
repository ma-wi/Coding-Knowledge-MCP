"""SQLAlchemy repository implementations for source metadata."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engineering_kb.domain.enums import SourceType
from engineering_kb.domain.identifiers import SourceId
from engineering_kb.domain.models import Source
from engineering_kb.persistence.orm_models import SourceRecord


class SqlAlchemySourceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, source_id: SourceId) -> Source | None:
        async with self._sessions() as session:
            record = await session.get(SourceRecord, str(source_id))
            return _to_domain(record) if record is not None else None

    async def list_enabled(self) -> Sequence[Source]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(SourceRecord).where(SourceRecord.enabled.is_(True)).order_by(SourceRecord.id)
            )
            return tuple(_to_domain(record) for record in result.all())

    async def upsert(self, source: Source) -> None:
        record = SourceRecord(
            id=str(source.id),
            source_type=source.source_type.value,
            name=source.name,
            enabled=source.enabled,
            trust_level=source.trust_level,
            configuration_json=source.configuration,
            last_successful_sync_at=source.last_successful_sync_at,
            last_error=source.last_error,
        )
        async with self._sessions() as session, session.begin():
            await session.merge(record)


def _to_domain(record: SourceRecord) -> Source:
    return Source(
        id=SourceId(record.id),
        source_type=SourceType(record.source_type),
        name=record.name,
        enabled=record.enabled,
        trust_level=record.trust_level,
        configuration=record.configuration_json,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_successful_sync_at=record.last_successful_sync_at,
        last_error=record.last_error,
    )
