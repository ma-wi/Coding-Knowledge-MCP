"""Typed configuration loaded from YAML with environment overrides."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from engineering_kb.domain.enums import Device, DistanceMetric, Precision
from engineering_kb.domain.errors import ConfigurationError
from engineering_kb.domain.identifiers import source_id


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BaseSourceConfig(StrictModel):
    id: str
    name: str | None = None
    enabled: bool = True
    trust_level: int = Field(ge=0, le=100)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        source_id(value)
        return value


class PdfDirectorySourceConfig(BaseSourceConfig):
    type: Literal["pdf_directory"]
    path: Path
    recursive: bool = True
    ocr_enabled: bool = False
    minimum_text_ratio: float = Field(default=0.05, ge=0, le=1)
    max_file_size_mb: int = Field(default=100, gt=0)


class WebsiteSourceConfig(BaseSourceConfig):
    type: Literal["website"]
    start_urls: list[HttpUrl] = Field(min_length=1)
    allowed_domains: list[str] = Field(min_length=1)
    allowed_paths: list[str] = Field(default_factory=lambda: ["/"])
    denied_paths: list[str] = Field(default_factory=list)
    max_depth: int = Field(default=4, ge=0, le=20)
    max_pages: int = Field(default=1500, gt=0)
    request_delay_ms: int = Field(default=250, ge=0)
    timeout_seconds: float = Field(default=20, gt=0)
    max_document_size_mb: int = Field(default=10, gt=0)
    retry_attempts: int = Field(default=2, ge=0, le=5)
    user_agent: str = Field(default="EngineeringKnowledgeBot/0.1", min_length=1, max_length=200)
    respect_robots_txt: bool = True

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            try:
                domain = value.encode("idna").decode("ascii").lower().rstrip(".")
            except UnicodeError as exc:
                raise ValueError("allowed domain is not a valid hostname") from exc
            if not domain or "://" in domain or "/" in domain or "@" in domain or ":" in domain:
                raise ValueError("allowed domains must contain hostnames only")
            normalized.append(domain)
        return normalized

    @field_validator("allowed_paths", "denied_paths")
    @classmethod
    def validate_path_prefixes(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("/") for value in values):
            raise ValueError("allowed and denied paths must start with '/'")
        return values


class GitSourceConfig(BaseSourceConfig):
    type: Literal["git"]
    url: str = Field(min_length=1)
    branch: str | None = None
    tag: str | None = None
    commit: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_file_size_mb: int = Field(default=10, gt=0)

    @model_validator(mode="after")
    def validate_revision_selection(self) -> GitSourceConfig:
        revisions = [value for value in (self.branch, self.tag, self.commit) if value]
        if len(revisions) > 1:
            raise ValueError("branch, tag, and commit are mutually exclusive")
        if self.commit and not all(
            character in "0123456789abcdefABCDEF" for character in self.commit
        ):
            raise ValueError("commit must be a hexadecimal object ID")
        for value in (self.branch, self.tag):
            if value and (
                value.startswith("-")
                or ".." in value
                or any(character in value for character in "~^:?*[\\\r\n\0")
            ):
                raise ValueError("branch and tag must be safe Git reference names")
        return self


class LocalDirectorySourceConfig(BaseSourceConfig):
    type: Literal["local_directory"]
    path: Path
    recursive: bool = True
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_file_size_mb: int = Field(default=10, gt=0)


SourceConfig = Annotated[
    PdfDirectorySourceConfig | WebsiteSourceConfig | GitSourceConfig | LocalDirectorySourceConfig,
    Field(discriminator="type"),
]


class SourcesConfig(StrictModel):
    version: Literal[1]
    sources: list[SourceConfig]

    @field_validator("sources")
    @classmethod
    def source_ids_are_unique(cls, values: list[SourceConfig]) -> list[SourceConfig]:
        identifiers = [item.id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("source IDs must be unique")
        return values


class DatabaseSettings(StrictModel):
    url: str = "sqlite+aiosqlite:///./data/engineering_kb.sqlite3"
    echo: bool = False


class QdrantSettings(StrictModel):
    url: str = "http://127.0.0.1:6333"
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=10, gt=0)


class LoggingSettings(StrictModel):
    level: str = "INFO"
    json_output: bool = Field(default=True, alias="json")
    redact_fields: list[str] = Field(
        default_factory=lambda: ["api_key", "authorization", "password", "token", "secret"]
    )


class EmbeddingProviderSettings(StrictModel):
    provider: Literal["local_transformers", "openai_compatible"]
    model: str
    revision: str | None = None
    dimension: int | None = Field(default=None, gt=0)
    device: Device = Device.AUTO
    precision: Precision = Precision.FP16
    batch_size: int = Field(default=8, gt=0)
    normalize: bool = True
    max_sequence_length: int = Field(default=2048, gt=0)
    pooling: str = "model_default"
    query_prefix: str = ""
    document_prefix: str = ""
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    base_url_env: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=30, gt=0)
    oom_retries: int = Field(default=2, ge=0, le=5)
    cpu_fallback: bool = True

    @field_validator("base_url_env", "api_key_env")
    @classmethod
    def validate_environment_variable_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("provider environment variable names must be valid identifiers")
        return value

    @model_validator(mode="after")
    def cloud_provider_has_endpoint(self) -> EmbeddingProviderSettings:
        if self.provider == "openai_compatible" and not self.base_url_env:
            raise ValueError("openai_compatible requires base_url_env")
        return self


class RerankerProviderSettings(StrictModel):
    provider: Literal["local_cross_encoder", "qwen_local", "http_reranker"]
    model: str
    revision: str | None = None
    device: Device = Device.AUTO
    precision: Precision = Precision.FP16
    batch_size: int = Field(default=4, gt=0)
    max_sequence_length: int = Field(default=1024, gt=0)
    base_url_env: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=30, gt=0)
    oom_retries: int = Field(default=2, ge=0, le=5)
    cpu_fallback: bool = True

    @field_validator("base_url_env", "api_key_env")
    @classmethod
    def validate_environment_variable_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("provider environment variable names must be valid identifiers")
        return value

    @model_validator(mode="after")
    def cloud_provider_has_endpoint(self) -> RerankerProviderSettings:
        if self.provider == "http_reranker" and not self.base_url_env:
            raise ValueError("http_reranker requires base_url_env")
        return self


class ActiveProfileSettings(StrictModel):
    embedding: str
    reranker: str


class ModelProfilesSettings(StrictModel):
    embeddings: dict[str, EmbeddingProviderSettings]
    rerankers: dict[str, RerankerProviderSettings]
    active_profiles: dict[str, ActiveProfileSettings]

    def validate_references(self) -> None:
        for name, profile in self.active_profiles.items():
            if profile.embedding not in self.embeddings:
                raise ValueError(f"profile {name!r} references unknown embedding")
            if profile.reranker not in self.rerankers:
                raise ValueError(f"profile {name!r} references unknown reranker")


class RetrievalSettings(StrictModel):
    dense_candidates: int = Field(default=30, gt=0)
    sparse_candidates: int = Field(default=30, gt=0)
    fusion_candidates: int = Field(default=40, gt=0)
    rerank_candidates: int = Field(default=20, gt=0)
    final_results: int = Field(default=6, gt=0)
    max_excerpt_tokens_per_result: int = Field(default=600, gt=0, le=600)
    max_total_tokens: int = Field(default=4500, gt=0, le=4500)
    minimum_score: float = Field(default=0.0, ge=0)
    rrf_k: int = Field(default=60, gt=0)
    diversification_enabled: bool = True
    max_results_per_document: int = Field(default=2, gt=0)
    max_results_per_source_version: int = Field(default=3, gt=0)
    near_duplicate_threshold: float = Field(default=0.9, ge=0, le=1)

    @model_validator(mode="after")
    def candidate_limits_are_consistent(self) -> RetrievalSettings:
        if self.fusion_candidates > self.dense_candidates + self.sparse_candidates:
            raise ValueError("fusion_candidates exceeds all retrieval candidates")
        if self.rerank_candidates > self.fusion_candidates:
            raise ValueError("rerank_candidates must not exceed fusion_candidates")
        if self.final_results > self.rerank_candidates:
            raise ValueError("final_results must not exceed rerank_candidates")
        return self


class ChunkingSettings(StrictModel):
    target_tokens: int = Field(default=700, ge=100)
    max_tokens: int = Field(default=900, ge=200)
    overlap_tokens: int = Field(default=80, ge=0)

    @field_validator("max_tokens")
    @classmethod
    def maximum_covers_target(cls, value: int, info: Any) -> int:
        target = info.data.get("target_tokens")
        if isinstance(target, int) and value < target:
            raise ValueError("max_tokens must be greater than or equal to target_tokens")
        return value

    @field_validator("overlap_tokens")
    @classmethod
    def overlap_is_bounded(cls, value: int, info: Any) -> int:
        maximum = info.data.get("max_tokens")
        if isinstance(maximum, int) and value > maximum * 0.15:
            raise ValueError("overlap_tokens must not exceed 15 percent of max_tokens")
        return value


class IngestionSettings(StrictModel):
    git_cache_path: Path = Path("data/git-cache")
    git_timeout_seconds: int = Field(default=120, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KB_", env_nested_delimiter="__", extra="forbid", case_sensitive=False
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    model_profiles: ModelProfilesSettings
    active_profile: str = "local_bge"
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    sources_file: Path = Path("config/sources.yaml")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, dotenv_settings, file_secret_settings
        return env_settings, init_settings

    def validate_profile_references(self) -> None:
        self.model_profiles.validate_references()
        if self.active_profile not in self.model_profiles.active_profiles:
            raise ValueError(f"unknown active profile: {self.active_profile}")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot load configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"configuration {path} must contain a YAML mapping")
    return value


def load_settings(path: Path) -> Settings:
    try:
        settings = Settings(**_load_yaml(path))
        settings.validate_profile_references()
        return settings
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"invalid settings configuration {path}: {exc}") from exc


def load_sources(path: Path) -> SourcesConfig:
    try:
        return SourcesConfig.model_validate(_load_yaml(path))
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"invalid sources configuration {path}: {exc}") from exc
