"""Evaluation dataset loading, execution, and report rendering."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engineering_kb.application.search_service import SearchRequest, SearchService
from engineering_kb.domain.evaluation import (
    EvaluationCase,
    EvaluationQueryResult,
    ProfileEvaluation,
    aggregate_metrics,
    evaluate_hits,
)
from engineering_kb.observability.hardware import inspect_hardware, reset_peak_memory

MAX_DATASET_BYTES = 10 * 1024 * 1024
MAX_CASES = 10_000
RECALL_AT_5_TARGET = 0.8


class EvaluationService:
    def __init__(
        self,
        search: SearchService,
        *,
        profile: str,
        embedding_profile: str,
        reranker_profile: str,
    ) -> None:
        self._search = search
        self._profile = profile
        self._embedding_profile = embedding_profile
        self._reranker_profile = reranker_profile

    async def evaluate(self, cases: tuple[EvaluationCase, ...]) -> ProfileEvaluation:
        if not cases:
            raise ValueError("evaluation dataset must contain at least one case")
        results: list[EvaluationQueryResult] = []
        for case in cases:
            reset_peak_memory()
            response = await self._search.search_with_diagnostics(
                SearchRequest(query=case.query, profile=self._profile, top_k=10)
            )
            hardware = inspect_hardware()
            metrics = evaluate_hits(
                case,
                response.hits,
                latency_seconds=response.diagnostics.total_seconds,
                embedding_latency_seconds=response.diagnostics.embedding_seconds,
                reranking_latency_seconds=response.diagnostics.reranking_seconds,
                gpu_peak_bytes=hardware.peak_allocated_vram_bytes or 0,
            )
            results.append(
                EvaluationQueryResult(
                    id=case.id,
                    category=case.category,
                    query=case.query,
                    metrics=metrics,
                    result_sources=tuple(str(hit.source_id) for hit in response.hits),
                    stable_references=tuple(hit.stable_key for hit in response.hits),
                )
            )
        query_results = tuple(results)
        aggregate = aggregate_metrics(query_results)
        return ProfileEvaluation(
            profile=self._profile,
            embedding_profile=self._embedding_profile,
            reranker_profile=self._reranker_profile,
            case_count=len(cases),
            recall_at_5_target=RECALL_AT_5_TARGET,
            recall_at_5_target_met=aggregate.recall_at_5 >= RECALL_AT_5_TARGET,
            metrics=aggregate,
            queries=query_results,
        )


def load_evaluation_cases(path: Path) -> tuple[EvaluationCase, ...]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"cannot inspect evaluation dataset {path}: {exc}") from exc
    if size > MAX_DATASET_BYTES:
        raise ValueError("evaluation dataset exceeds 10 MiB")
    cases: list[EvaluationCase] = []
    identifiers: set[str] = set()
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                if len(cases) >= MAX_CASES:
                    raise ValueError(f"evaluation dataset exceeds {MAX_CASES} cases")
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
                case = _parse_case(raw, line_number)
                if case.id in identifiers:
                    raise ValueError(f"duplicate evaluation ID on line {line_number}: {case.id}")
                identifiers.add(case.id)
                cases.append(case)
    except OSError as exc:
        raise ValueError(f"cannot read evaluation dataset {path}: {exc}") from exc
    if not cases:
        raise ValueError("evaluation dataset must contain at least one case")
    return tuple(cases)


def write_evaluation_reports(
    reports: tuple[ProfileEvaluation, ...], output_directory: Path
) -> tuple[Path, Path]:
    if not reports:
        raise ValueError("at least one profile report is required")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"evaluation-{timestamp}"
    json_path = output_directory / f"{stem}.json"
    markdown_path = output_directory / f"{stem}.md"
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "profiles": [report.as_dict() for report in reports],
    }
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(markdown_path, render_markdown_report(reports))
    return json_path, markdown_path


def render_markdown_report(reports: tuple[ProfileEvaluation, ...]) -> str:
    lines = [
        "# Knowledge-base evaluation",
        "",
        "| Profile | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@5 | Precision@5 | "
        "Avg latency | Embed | Rerank | GPU peak | Avg tokens | Near duplicates | "
        "Source diversity | Target |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for report in reports:
        metric = report.metrics
        lines.append(
            f"| {_markdown(report.profile)} | {metric.recall_at_1:.3f} | "
            f"{metric.recall_at_5:.3f} | "
            f"{metric.recall_at_10:.3f} | {metric.mrr:.3f} | {metric.ndcg_at_5:.3f} | "
            f"{metric.precision_at_5:.3f} | {metric.average_latency_seconds:.3f}s | "
            f"{metric.average_embedding_latency_seconds:.3f}s | "
            f"{metric.average_reranking_latency_seconds:.3f}s | "
            f"{_bytes(metric.gpu_peak_bytes)} | {metric.average_result_tokens:.1f} | "
            f"{metric.near_duplicate_rate:.3f} | {metric.source_diversity:.3f} | "
            f"{'yes' if report.recall_at_5_target_met else 'no'} |"
        )
    lines.extend(["", "Recall@5 target: 0.800.", ""])
    for report in reports:
        lines.extend([f"## {_markdown(report.profile)}", "", f"Cases: {report.case_count}", ""])
        lines.extend(
            [
                "| Case | Category | Recall@5 | MRR | Latency |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for result in report.queries:
            lines.append(
                f"| {_markdown(result.id)} | {_markdown(result.category)} | "
                f"{result.metrics.recall_at_5:.3f} | {result.metrics.reciprocal_rank:.3f} | "
                f"{result.metrics.latency_seconds:.3f}s |"
            )
        lines.append("")
    return "\n".join(lines)


def _parse_case(raw: Any, line_number: int) -> EvaluationCase:
    if not isinstance(raw, Mapping):
        raise ValueError(f"evaluation case on line {line_number} must be an object")
    allowed = {"id", "query", "expected_sources", "expected_terms", "category"}
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown or missing:
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown {', '.join(sorted(unknown))}")
        raise ValueError(f"invalid evaluation case on line {line_number}: {'; '.join(details)}")
    identifier = _bounded_string(raw["id"], "id", line_number, 200)
    query = _bounded_string(raw["query"], "query", line_number, 2_000)
    category = _bounded_string(raw["category"], "category", line_number, 100)
    sources = _string_list(raw["expected_sources"], "expected_sources", line_number, 100, 200)
    terms = _string_list(raw["expected_terms"], "expected_terms", line_number, 100, 200)
    return EvaluationCase(identifier, query, sources, terms, category)


def _bounded_string(value: Any, name: str, line: int, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(
            f"{name} on line {line} must be a non-empty string of at most {maximum} characters"
        )
    return value.strip()


def _string_list(
    value: Any, name: str, line: int, maximum_items: int, maximum_length: int
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum_items
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > maximum_length
            for item in value
        )
    ):
        raise ValueError(f"{name} on line {line} must be a bounded list of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} on line {line} must not contain duplicates")
    return normalized


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
