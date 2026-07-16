"""明確設定且支援多行程安全的應用程式日誌。"""

# ruff: noqa: RUF003

# 對外介面集中在套件入口，實作細節維持私有。
from ._formatters import DEFAULT_LOG_FORMAT
from ._runtime import configure_logging, shutdown_logging
from .exceptions import LoggingAlreadyConfiguredError, LoggingConfigurationError

__all__ = [
    "DEFAULT_LOG_FORMAT",
    "LoggingAlreadyConfiguredError",
    "LoggingConfigurationError",
    "configure_logging",
    "shutdown_logging",
]
