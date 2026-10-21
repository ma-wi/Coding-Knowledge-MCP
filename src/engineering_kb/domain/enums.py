"""Domain enumerations shared by application ports."""

from enum import StrEnum


class SourceType(StrEnum):
    PDF_DIRECTORY = "pdf_directory"
    WEBSITE = "website"
    GIT = "git"
    LOCAL_DIRECTORY = "local_directory"


class SourceVersionStatus(StrEnum):
    DISCOVERED = "discovered"
    INDEXING = "indexing"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"


class SyncTrigger(StrEnum):
    CLI = "cli"


class ContentType(StrEnum):
    OFFICIAL_DOCUMENTATION = "official_documentation"
    ARCHITECTURE = "architecture"
    DESIGN_PATTERN = "design_pattern"
    CODING_GUIDELINE = "coding_guideline"
    API_DOCUMENTATION = "api_documentation"
    SOURCE_CODE = "source_code"
    TEST = "test"
    EXAMPLE = "example"
    TUTORIAL = "tutorial"
    README = "readme"
    ADR = "adr"
    CONFIGURATION = "configuration"
    TABLE = "table"
    OPINION = "opinion"
    UNKNOWN = "unknown"


class Device(StrEnum):
    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


class Precision(StrEnum):
    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    INT8 = "int8"


class DistanceMetric(StrEnum):
    COSINE = "cosine"
    DOT = "dot"
    EUCLID = "euclid"
