"""Redis-backed coordination locks."""

from .exceptions import (
    LockAcquisitionTimeout,
    LockBackendUnavailable,
    LockError,
    LockLostError,
)
from .manager import RedisLockManager

__all__ = [
    "LockAcquisitionTimeout",
    "LockBackendUnavailable",
    "LockError",
    "LockLostError",
    "RedisLockManager",
]
