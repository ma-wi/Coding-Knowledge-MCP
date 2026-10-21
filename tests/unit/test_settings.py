from pathlib import Path

import pytest

from engineering_kb.domain.errors import ConfigurationError
from engineering_kb.settings import load_settings, load_sources

PROJECT_ROOT = Path(__file__).parents[2]


def test_example_configuration_is_valid() -> None:
    settings = load_settings(PROJECT_ROOT / "config/settings.example.yaml")
    sources = load_sources(PROJECT_ROOT / "config/sources.example.yaml")

    assert settings.active_profile == "local_bge"
    assert settings.model_profiles.active_profiles["local_bge"].embedding == "local_bge_m3"
    assert {
        "local-pdfs",
        "fastapi-docs",
        "python-patterns",
    } <= {source.id for source in sources.sources}


def test_environment_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_LOGGING__LEVEL", "DEBUG")
    settings = load_settings(PROJECT_ROOT / "config/settings.example.yaml")
    assert settings.logging.level == "DEBUG"


def test_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        """version: 1
sources:
  - {id: duplicate, type: pdf_directory, path: one, trust_level: 50}
  - {id: duplicate, type: pdf_directory, path: two, trust_level: 50}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="source IDs must be unique"):
        load_sources(path)


def test_unknown_profile_reference_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        """model_profiles:
  embeddings: {}
  rerankers: {}
  active_profiles:
    broken: {embedding: missing, reranker: missing}
active_profile: broken
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="unknown embedding"):
        load_settings(path)


def test_cloud_provider_requires_environment_variable_name(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        """model_profiles:
  embeddings:
    cloud: {provider: openai_compatible, model: remote}
  rerankers:
    local: {provider: local_cross_encoder, model: local}
  active_profiles:
    cloud: {embedding: cloud, reranker: local}
active_profile: cloud
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="base_url_env"):
        load_settings(path)
