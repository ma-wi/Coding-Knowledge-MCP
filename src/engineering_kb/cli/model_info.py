"""GPU inspection and bounded model benchmark orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from time import perf_counter
from typing import Any

from engineering_kb.domain.identifiers import ChunkId
from engineering_kb.domain.models import ModelRuntimeInfo, RerankDocument
from engineering_kb.embeddings.registry import create_embedding_provider
from engineering_kb.observability.hardware import inspect_hardware, reset_peak_memory
from engineering_kb.reranking.registry import create_reranking_provider
from engineering_kb.settings import Settings

_SAMPLES = [
    "FastAPI dependency injection provides reusable database sessions.",
    "A repository isolates persistence from application logic.",
    "Tests should verify observable behavior and failure handling.",
]


def inspect_profile(settings: Settings, profile_name: str | None) -> dict[str, Any]:
    selected_name = profile_name or settings.active_profile
    selected = settings.model_profiles.active_profiles[selected_name]
    embedding = settings.model_profiles.embeddings[selected.embedding]
    reranker = settings.model_profiles.rerankers[selected.reranker]
    return {
        "profile": selected_name,
        "hardware": inspect_hardware().as_dict(),
        "embedding": embedding.model_dump(mode="json", exclude={"api_key_env"}),
        "reranker": reranker.model_dump(mode="json", exclude={"api_key_env"}),
        "parameter_count": None,
        "estimated_model_bytes": None,
        "loaded": False,
    }


async def benchmark_profile(settings: Settings, profile_name: str | None) -> dict[str, Any]:
    selected_name = profile_name or settings.active_profile
    selected = settings.model_profiles.active_profiles[selected_name]
    embedding = create_embedding_provider(settings.model_profiles.embeddings[selected.embedding])
    reranker = create_reranking_provider(settings.model_profiles.rerankers[selected.reranker])
    try:
        reset_peak_memory()
        started = perf_counter()
        await embedding.embed_documents(_SAMPLES)
        embedding_latency = perf_counter() - started
        documents = [
            RerankDocument(id=ChunkId(str(index)), text=text) for index, text in enumerate(_SAMPLES)
        ]
        started = perf_counter()
        await reranker.rerank("dependency injection", documents, top_k=len(documents))
        reranking_latency = perf_counter() - started
        return {
            "profile": selected_name,
            "hardware": inspect_hardware().as_dict(),
            "embedding_latency_seconds": embedding_latency,
            "reranking_latency_seconds": reranking_latency,
            "embedding_runtime": _runtime(embedding),
            "reranker_runtime": _runtime(reranker),
        }
    finally:
        await _close(embedding)
        await _close(reranker)


def run_benchmark(settings: Settings, profile_name: str | None) -> dict[str, Any]:
    return asyncio.run(benchmark_profile(settings, profile_name))


def _runtime(provider: object) -> dict[str, Any] | None:
    value = getattr(provider, "runtime", None)
    if not isinstance(value, ModelRuntimeInfo):
        return None
    result = asdict(value)
    result["maximum_successful_batch_size"] = value.batch_size
    return result


async def _close(provider: object) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        result = close()
        if hasattr(result, "__await__"):
            await result
