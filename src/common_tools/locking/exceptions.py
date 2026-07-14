__all__ = [
    "LockAcquisitionTimeout",
    "LockBackendUnavailable",
    "LockError",
    "LockLostError",
]


class LockError(Exception):
    """Base class for Redis lock failures."""


class LockBackendUnavailable(LockError):
    """Raised when Redis cannot perform a lock operation."""


class LockAcquisitionTimeout(LockError):
    """Raised when a lock cannot be acquired before its deadline."""


class LockLostError(LockError):
    """Raised when work must stop because its lease was lost."""
