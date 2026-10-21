from engineering_kb.application.source_service import SourceService
from engineering_kb.settings import SourcesConfig


def test_source_queries_are_infrastructure_independent() -> None:
    configuration = SourcesConfig.model_validate(
        {
            "version": 1,
            "sources": [
                {
                    "id": "enabled",
                    "type": "pdf_directory",
                    "path": "pdfs",
                    "enabled": True,
                    "trust_level": 80,
                },
                {
                    "id": "disabled",
                    "type": "local_directory",
                    "path": "code",
                    "enabled": False,
                    "trust_level": 60,
                },
            ],
        }
    )
    service = SourceService(configuration)

    assert [source.id for source in service.list(enabled_only=True)] == ["enabled"]
    assert service.inspect("disabled") is not None
    assert service.inspect("missing") is None
