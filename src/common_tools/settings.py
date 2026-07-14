"""Process-wide settings lifecycle with context-local test overrides."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar


class SettingsNotInitializedError(RuntimeError):
    """Raised when settings are requested before initialization."""


class SettingsAlreadyInitializedError(RuntimeError):
    """Raised when process-wide settings are initialized more than once."""


class _Unset:
    """Sentinel distinguishing a missing value from any valid settings value."""


_UNSET = _Unset()


class SettingsProvider[T]:
    """Own one process-wide settings instance with context-local overrides.

    The provider is deliberately independent of any settings library. Passing a
    ``pydantic_settings.BaseSettings`` subclass as the factory preserves that
    class's environment loading and validation behavior.
    """

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._settings: T | _Unset = _UNSET
        self._override: ContextVar[T | _Unset] = ContextVar(
            f"settings_override_{id(self)}",
            default=_UNSET,
        )

    def initialize(self) -> T:
        """Create and retain the process-wide settings instance."""
        if not isinstance(self._settings, _Unset):
            raise SettingsAlreadyInitializedError("settings are already initialized")

        settings = self._factory()
        self._settings = settings
        return settings

    def get(self) -> T:
        """Return the context override or the process-wide settings instance."""
        override = self._override.get()
        if not isinstance(override, _Unset):
            return override

        if isinstance(self._settings, _Unset):
            raise SettingsNotInitializedError("settings are not initialized")
        return self._settings

    @contextmanager
    def override(self, settings: T) -> Generator[T]:
        """Temporarily override settings in the current execution context."""
        token = self._override.set(settings)
        try:
            yield settings
        finally:
            self._override.reset(token)


__all__ = [
    "SettingsAlreadyInitializedError",
    "SettingsNotInitializedError",
    "SettingsProvider",
]
