__all__ = [
    "DatabaseConnectionError",
    "DatabaseError",
    "DatabaseNotStartedError",
]


class DatabaseError(Exception):
    """Base class for database module failures."""


class DatabaseNotStartedError(DatabaseError):
    """Raised when a database operation is attempted before startup."""


class DatabaseConnectionError(DatabaseError):
    """Raised when PostgreSQL startup or a health check fails."""
