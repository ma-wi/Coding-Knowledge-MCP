"""Milestone 1 command-line interface."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from engineering_kb import __version__
from engineering_kb.cli.evaluate import run_evaluation
from engineering_kb.cli.model_info import inspect_profile, run_benchmark
from engineering_kb.cli.search import run_search
from engineering_kb.cli.sync import run_sync
from engineering_kb.domain.errors import ConfigurationError
from engineering_kb.settings import load_settings, load_sources

app = typer.Typer(
    name="kb",
    help="Manage the local engineering knowledge base.",
    no_args_is_help=True,
    add_completion=False,
)
models_app = typer.Typer(help="Inspect and benchmark configured model profiles.")
app.add_typer(models_app, name="models")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Manage the local engineering knowledge base."""
    del version


@app.command("validate-config")
def validate_config(
    settings_path: Annotated[
        Path,
        typer.Option("--settings", help="Settings YAML file.", exists=True, dir_okay=False),
    ] = Path("config/settings.yaml"),
    sources_path: Annotated[
        Path | None,
        typer.Option("--sources", help="Override sources YAML file.", exists=True, dir_okay=False),
    ] = None,
) -> None:
    """Validate all configuration before a synchronization run."""
    try:
        settings = load_settings(settings_path)
        selected_sources = sources_path or settings.sources_file
        sources = load_sources(selected_sources)
    except ConfigurationError as exc:
        typer.echo(f"Configuration invalid: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"Configuration valid: {len(sources.sources)} sources, "
        f"{len(settings.model_profiles.active_profiles)} active profiles"
    )


@app.command("sync")
def sync_command(
    source: Annotated[str | None, typer.Option("--source", help="Synchronize one source.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Rebuild unchanged documents.")] = False,
    profile: Annotated[str | None, typer.Option("--profile", help="Allowed model profile.")] = None,
    settings_path: Annotated[Path, typer.Option("--settings", exists=True, dir_okay=False)] = Path(
        "config/settings.yaml"
    ),
    sources_path: Annotated[
        Path | None, typer.Option("--sources", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Synchronize configured PDF, Git, and website sources manually."""
    try:
        settings = load_settings(settings_path)
        if profile is not None and profile not in settings.model_profiles.active_profiles:
            raise ConfigurationError(f"profile is not allowed: {profile}")
        sources = load_sources(sources_path or settings.sources_file)
        result = run_sync(
            settings,
            sources,
            selected_source=source,
            force=force,
            profile=profile,
        )
    except (ConfigurationError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Synchronization failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for message in result.messages:
        typer.echo(message)
    if result.failed_sources:
        raise typer.Exit(code=1)


@app.command("search")
def search_command(
    query: Annotated[str, typer.Argument(help="Technical question or search terms.")],
    profile: Annotated[str | None, typer.Option("--profile", help="Allowed model profile.")] = None,
    source: Annotated[str | None, typer.Option("--source", help="Restrict to one source.")] = None,
    top_k: Annotated[int | None, typer.Option("--top-k", min=1, max=20)] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    settings_path: Annotated[Path, typer.Option("--settings", exists=True, dir_okay=False)] = Path(
        "config/settings.yaml"
    ),
) -> None:
    """Search all active sources through dense and BM25 retrieval."""
    try:
        settings = load_settings(settings_path)
        if profile is not None and profile not in settings.model_profiles.active_profiles:
            raise ConfigurationError(f"profile is not allowed: {profile}")
        hits = run_search(
            settings,
            query,
            profile=profile,
            source=source,
            top_k=top_k,
        )
    except (ConfigurationError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Search failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
        return
    for rank, hit in enumerate(hits, start=1):
        location = hit.location.get("page") or hit.location.get("path") or hit.location.get("url")
        typer.echo(f"{rank}. {hit.title} ({location or '?'}, score={hit.score:.4f})")
        typer.echo(hit.excerpt)
        typer.echo(f"source: {hit.stable_key}")


@app.command("evaluate", context_settings={"allow_extra_args": True})
def evaluate_command(
    context: typer.Context,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Evaluate one allowed model profile.")
    ] = None,
    compare: Annotated[
        list[str] | None,
        typer.Option("--compare", help="Evaluate and compare multiple model profiles."),
    ] = None,
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset", help="Curated JSONL evaluation dataset.", exists=True, dir_okay=False
        ),
    ] = Path("evaluation/questions.jsonl"),
    output_directory: Annotated[
        Path, typer.Option("--output-dir", help="Directory for JSON and Markdown reports.")
    ] = Path("reports/evaluation"),
    settings_path: Annotated[Path, typer.Option("--settings", exists=True, dir_okay=False)] = Path(
        "config/settings.yaml"
    ),
) -> None:
    """Evaluate retrieval quality and compare configured model profiles."""
    try:
        settings = load_settings(settings_path)
        if profile is not None and compare:
            raise ConfigurationError("--profile and --compare are mutually exclusive")
        if context.args and not compare:
            raise ConfigurationError(f"unexpected arguments: {' '.join(context.args)}")
        profiles = (*compare, *context.args) if compare else (profile or settings.active_profile,)
        if len(profiles) != len(set(profiles)):
            raise ConfigurationError("evaluation profiles must be unique")
        unknown = [name for name in profiles if name not in settings.model_profiles.active_profiles]
        if unknown:
            raise ConfigurationError(f"profile is not allowed: {', '.join(unknown)}")
        reports, json_path, markdown_path = run_evaluation(
            settings,
            dataset,
            output_directory,
            profiles,
        )
    except (ConfigurationError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Evaluation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for report in reports:
        target = "met" if report.recall_at_5_target_met else "not met"
        typer.echo(f"{report.profile}: Recall@5={report.metrics.recall_at_5:.3f} (target {target})")
    typer.echo(f"JSON report: {json_path}")
    typer.echo(f"Markdown report: {markdown_path}")


@models_app.command("inspect")
def models_inspect_command(
    profile: Annotated[str | None, typer.Option("--profile", help="Allowed model profile.")] = None,
    settings_path: Annotated[Path, typer.Option("--settings", exists=True, dir_okay=False)] = Path(
        "config/settings.yaml"
    ),
) -> None:
    """Inspect CUDA and the selected model configuration without loading models."""
    try:
        settings = load_settings(settings_path)
        if profile is not None and profile not in settings.model_profiles.active_profiles:
            raise ConfigurationError(f"profile is not allowed: {profile}")
        result = inspect_profile(settings, profile)
    except (ConfigurationError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Model inspection failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@models_app.command("benchmark")
def models_benchmark_command(
    profile: Annotated[str | None, typer.Option("--profile", help="Allowed model profile.")] = None,
    settings_path: Annotated[Path, typer.Option("--settings", exists=True, dir_okay=False)] = Path(
        "config/settings.yaml"
    ),
) -> None:
    """Load embedding and reranking models and run a bounded sample benchmark."""
    try:
        settings = load_settings(settings_path)
        if profile is not None and profile not in settings.model_profiles.active_profiles:
            raise ConfigurationError(f"profile is not allowed: {profile}")
        result = run_benchmark(settings, profile)
    except (ConfigurationError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"Model benchmark failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
