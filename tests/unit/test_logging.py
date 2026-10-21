import pytest

from engineering_kb.observability.logging import configure_logging, get_logger
from engineering_kb.settings import LoggingSettings


def test_sensitive_fields_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingSettings(json_output=True))
    get_logger("test").info("request", api_key="do-not-print", source_id="safe")

    captured = capsys.readouterr()
    assert "do-not-print" not in captured.err
    assert "[REDACTED]" in captured.err
    assert captured.out == ""
