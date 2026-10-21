"""Application-safe domain errors."""


class KnowledgeBaseError(Exception):
    """Base class for expected knowledge-base failures."""


class ConfigurationError(KnowledgeBaseError):
    """Raised when configuration cannot be loaded or validated."""


class CompatibilityError(KnowledgeBaseError):
    """Raised for incompatible model and index profiles."""


class RepositoryError(KnowledgeBaseError):
    """Raised by persistence ports without leaking driver details."""


class FeatureNotAvailableError(KnowledgeBaseError):
    """Raised when a later-milestone capability is invoked prematurely."""
