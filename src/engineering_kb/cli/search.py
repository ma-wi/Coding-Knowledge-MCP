"""Dense CLI search orchestration."""

import asyncio

from engineering_kb.application.search_service import SearchRequest
from engineering_kb.bootstrap import build_services
from engineering_kb.domain.models import SearchHit
from engineering_kb.settings import Settings


async def search(
    settings: Settings,
    query: str,
    *,
    profile: str | None,
    source: str | None,
    top_k: int | None,
) -> tuple[SearchHit, ...]:
    services = build_services(settings, profile)
    try:
        filters = {"source_ids": [source]} if source else {}
        return await services.search.search(
            SearchRequest(query=query, profile=profile, filters=filters, top_k=top_k)
        )
    finally:
        await services.close()


def run_search(
    settings: Settings,
    query: str,
    *,
    profile: str | None,
    source: str | None,
    top_k: int | None,
) -> tuple[SearchHit, ...]:
    return asyncio.run(search(settings, query, profile=profile, source=source, top_k=top_k))
