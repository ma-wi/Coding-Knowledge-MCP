"""Source configuration queries shared by future adapters."""

from engineering_kb.settings import SourceConfig, SourcesConfig


class SourceService:
    def __init__(self, configuration: SourcesConfig) -> None:
        self._configuration = configuration

    def list(self, *, enabled_only: bool = False) -> tuple[SourceConfig, ...]:
        return tuple(
            source for source in self._configuration.sources if not enabled_only or source.enabled
        )

    def inspect(self, source_id: str) -> SourceConfig | None:
        return next(
            (source for source in self._configuration.sources if source.id == source_id), None
        )
