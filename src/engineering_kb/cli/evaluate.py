"""Evaluation CLI orchestration with one bounded service lifecycle per profile."""

import asyncio
from pathlib import Path

from engineering_kb.application.evaluation_service import (
    EvaluationService,
    load_evaluation_cases,
    write_evaluation_reports,
)
from engineering_kb.bootstrap import build_services
from engineering_kb.domain.evaluation import ProfileEvaluation
from engineering_kb.settings import Settings


async def evaluate_profiles(
    settings: Settings,
    dataset: Path,
    profiles: tuple[str, ...],
) -> tuple[ProfileEvaluation, ...]:
    cases = load_evaluation_cases(dataset)
    reports: list[ProfileEvaluation] = []
    for profile in profiles:
        services = build_services(settings, profile)
        try:
            evaluator = EvaluationService(
                services.search,
                profile=profile,
                embedding_profile=services.embedding_profile_name,
                reranker_profile=services.reranker_profile_name,
            )
            reports.append(await evaluator.evaluate(cases))
        finally:
            await services.close()
    return tuple(reports)


def run_evaluation(
    settings: Settings,
    dataset: Path,
    output_directory: Path,
    profiles: tuple[str, ...],
) -> tuple[tuple[ProfileEvaluation, ...], Path, Path]:
    reports = asyncio.run(evaluate_profiles(settings, dataset, profiles))
    json_path, markdown_path = write_evaluation_reports(reports, output_directory)
    return reports, json_path, markdown_path
