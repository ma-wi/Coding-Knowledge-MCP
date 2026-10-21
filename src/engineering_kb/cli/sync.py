"""PDF synchronization CLI orchestration."""

import asyncio
from dataclasses import dataclass

from engineering_kb.bootstrap import build_services
from engineering_kb.settings import (
    GitSourceConfig,
    PdfDirectorySourceConfig,
    Settings,
    SourcesConfig,
    WebsiteSourceConfig,
)


@dataclass(frozen=True, slots=True)
class SyncCliResult:
    messages: tuple[str, ...]
    failed_sources: int


async def synchronize_sources(
    settings: Settings,
    sources: SourcesConfig,
    *,
    selected_source: str | None,
    force: bool,
    profile: str | None,
) -> SyncCliResult:
    services = build_services(settings, profile)
    messages: list[str] = []
    failures = 0
    try:
        candidates = [
            source
            for source in sources.sources
            if source.enabled and (selected_source is None or source.id == selected_source)
        ]
        if selected_source is not None and not candidates:
            raise ValueError(f"enabled source not found: {selected_source}")
        for source in candidates:
            if not isinstance(
                source, (PdfDirectorySourceConfig, GitSourceConfig, WebsiteSourceConfig)
            ):
                messages.append(f"{source.id}: skipped (supported in a later milestone)")
                continue
            try:
                if isinstance(source, PdfDirectorySourceConfig):
                    summary = await services.sync.synchronize(source, force=force)
                elif isinstance(source, GitSourceConfig):
                    summary = await services.git_sync.synchronize(source, force=force)
                else:
                    summary = await services.web_sync.synchronize(source, force=force)
            except Exception as exc:  # Sources must remain isolated from each other.
                failures += 1
                try:
                    if isinstance(source, PdfDirectorySourceConfig):
                        await services.sync.record_failure(source, exc)
                    elif isinstance(source, GitSourceConfig):
                        await services.git_sync.record_failure(source, exc)
                    else:
                        await services.web_sync.record_failure(source, exc)
                except Exception:
                    pass
                messages.append(f"{source.id}: failed ({type(exc).__name__}: {exc})")
                continue
            if summary.unchanged:
                messages.append(f"{source.id}: unchanged")
            else:
                messages.append(
                    f"{source.id}: added={summary.documents_added} "
                    f"updated={summary.documents_updated} deleted={summary.documents_deleted} "
                    f"embedded_chunks={summary.chunks_embedded}"
                )
    finally:
        await services.close()
    return SyncCliResult(tuple(messages), failures)


def run_sync(
    settings: Settings,
    sources: SourcesConfig,
    *,
    selected_source: str | None,
    force: bool,
    profile: str | None,
) -> SyncCliResult:
    return asyncio.run(
        synchronize_sources(
            settings,
            sources,
            selected_source=selected_source,
            force=force,
            profile=profile,
        )
    )
