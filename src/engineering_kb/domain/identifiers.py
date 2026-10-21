"""Validated identifiers used at domain boundaries."""

import re
from typing import NewType

SourceId = NewType("SourceId", str)
DocumentId = NewType("DocumentId", str)
ChunkId = NewType("ChunkId", str)

_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


def source_id(value: str) -> SourceId:
    """Create a source identifier after enforcing its stable wire format."""
    if not _SOURCE_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "source ID must be 1-64 lowercase ASCII characters and may contain '-' or '_'"
        )
    return SourceId(value)
