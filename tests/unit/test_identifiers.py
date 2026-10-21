import pytest

from engineering_kb.domain.identifiers import source_id


@pytest.mark.parametrize("value", ["pdfs", "fastapi-docs", "project_2", "a"])
def test_source_id_accepts_stable_identifiers(value: str) -> None:
    assert source_id(value) == value


@pytest.mark.parametrize("value", ["", "UPPER", "has space", "-prefix", "suffix-"])
def test_source_id_rejects_unsafe_identifiers(value: str) -> None:
    with pytest.raises(ValueError):
        source_id(value)
