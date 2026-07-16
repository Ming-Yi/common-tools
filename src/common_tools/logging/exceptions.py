"""應用程式日誌設定可能拋出的例外。"""

__all__ = ["LoggingAlreadyConfiguredError", "LoggingConfigurationError"]


class LoggingConfigurationError(RuntimeError):
    """無法安全初始化日誌時拋出。"""


class LoggingAlreadyConfiguredError(LoggingConfigurationError):
    """行程嘗試取代使用中的日誌設定時拋出。"""
