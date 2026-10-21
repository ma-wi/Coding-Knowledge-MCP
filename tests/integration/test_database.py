import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from engineering_kb.domain.enums import SourceType
from engineering_kb.domain.identifiers import source_id
from engineering_kb.domain.models import Source
from engineering_kb.persistence.database import create_engine, create_session_factory
from engineering_kb.persistence.repositories import SqlAlchemySourceRepository


async def test_initial_migration_and_source_repository(tmp_path: Path) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    configuration = Config("alembic.ini")
    configuration.set_main_option("sqlalchemy.url", database_url)
    await asyncio.to_thread(command.upgrade, configuration, "head")

    engine = create_engine(database_url)
    async with engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert {
        "sources",
        "source_versions",
        "documents",
        "chunks",
        "sync_runs",
        "search_logs",
        "chunk_fts",
    }.issubset(table_names)

    repository = SqlAlchemySourceRepository(create_session_factory(engine))
    await repository.upsert(
        Source(
            id=source_id("local-pdfs"),
            source_type=SourceType.PDF_DIRECTORY,
            name="PDFs",
            enabled=True,
            trust_level=80,
            configuration={"path": "knowledge_base"},
        )
    )
    stored = await repository.get(source_id("local-pdfs"))
    assert stored is not None
    assert stored.trust_level == 80
    assert [source.id for source in await repository.list_enabled()] == ["local-pdfs"]
    await engine.dispose()


async def test_bm25_migration_backfills_an_active_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "backfill.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    configuration = Config("alembic.ini")
    configuration.set_main_option("sqlalchemy.url", database_url)
    await asyncio.to_thread(command.upgrade, configuration, "0001")
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO sources
                    (id, source_type, name, enabled, trust_level, configuration_json,
                     created_at, updated_at)
                VALUES ('repo', 'git', 'Repo', 1, 80, '{}', CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP);
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO source_versions
                    (id, source_id, version_identifier, status, discovered_at, metadata_json)
                VALUES ('version', 'repo', 'v1', 'active', CURRENT_TIMESTAMP,
                        '{"embedding_profile":"fake"}');
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO documents
                    (id, source_version_id, logical_path, title, content_hash,
                     metadata_json, enabled)
                VALUES ('document', 'version', 'src/repository.py', 'Repository',
                        'document-hash', '{}', 1);
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO chunks
                    (id, document_id, stable_key, ordinal, heading_path, content,
                     content_type, token_count, location_json, content_hash, enabled,
                     embedding_profile)
                VALUES ('chunk', 'document', 'git:repo:v1:src/repository.py:BaseRepository',
                        0, '["BaseRepository"]', 'class BaseRepository: pass',
                        'source_code', 4, '{}', 'chunk-hash', 1, 'fake');
                """
            )
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, configuration, "head")
    engine = create_engine(database_url)
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'baserepository'")
        )
    assert count == 1
    await engine.dispose()
