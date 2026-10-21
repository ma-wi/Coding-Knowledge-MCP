from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from engineering_kb.application.sync_service import SyncSummary
from engineering_kb.cli import sync as cli_sync
from engineering_kb.cli.main import app
from engineering_kb.settings import (
    PdfDirectorySourceConfig,
    SourcesConfig,
    load_settings,
    load_sources,
)

PROJECT_ROOT = Path(__file__).parents[2]
runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_validate_example_configuration() -> None:
    configured_sources = load_sources(PROJECT_ROOT / "config/sources.example.yaml")
    result = runner.invoke(
        app,
        [
            "validate-config",
            "--settings",
            str(PROJECT_ROOT / "config/settings.example.yaml"),
            "--sources",
            str(PROJECT_ROOT / "config/sources.example.yaml"),
        ],
    )
    assert result.exit_code == 0
    assert f"Configuration valid: {len(configured_sources.sources)} sources" in result.stdout


def test_models_inspect_does_not_load_models() -> None:
    result = runner.invoke(
        app,
        ["models", "inspect", "--settings", str(PROJECT_ROOT / "config/settings.example.yaml")],
    )
    assert result.exit_code == 0
    assert '"profile": "local_bge"' in result.stdout
    assert '"loaded": false' in result.stdout


def test_evaluate_compare_accepts_space_separated_profiles() -> None:
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--compare",
            "local_bge",
            "local_bge",
            "--settings",
            str(PROJECT_ROOT / "config/settings.example.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "evaluation profiles must be unique" in result.stderr


async def test_failed_source_does_not_block_following_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = load_settings(PROJECT_ROOT / "config/settings.example.yaml")
    pdf_sync = SimpleNamespace(
        synchronize=AsyncMock(
            side_effect=[
                RuntimeError("broken source"),
                SyncSummary("healthy", "v1", documents_added=1),
            ]
        ),
        record_failure=AsyncMock(),
    )
    services = SimpleNamespace(sync=pdf_sync, close=AsyncMock())
    monkeypatch.setattr(cli_sync, "build_services", lambda _settings, _profile: services)
    sources = SourcesConfig(
        version=1,
        sources=[
            PdfDirectorySourceConfig(
                id="broken", type="pdf_directory", path=tmp_path, trust_level=80
            ),
            PdfDirectorySourceConfig(
                id="healthy", type="pdf_directory", path=tmp_path, trust_level=80
            ),
        ],
    )

    result = await cli_sync.synchronize_sources(
        settings, sources, selected_source=None, force=False, profile=None
    )

    assert result.failed_sources == 1
    assert result.messages[0].startswith("broken: failed")
    assert result.messages[1].startswith("healthy: added=1")
    assert pdf_sync.synchronize.await_count == 2
    pdf_sync.record_failure.assert_awaited_once()
