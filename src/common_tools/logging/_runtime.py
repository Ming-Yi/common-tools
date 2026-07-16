"""管理行程層級的日誌安裝、關閉與 fork 生命週期。"""

# ruff: noqa: RUF002, RUF003

import logging
import os
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Literal

from ._config import UNSET, LoggingConfig, load_timezone, resolve_config
from ._formatters import TimezoneFormatter, stream_supports_color
from ._handlers import DailyConcurrentFileHandler
from .exceptions import LoggingAlreadyConfiguredError, LoggingConfigurationError

__all__ = ["configure_logging", "shutdown_logging"]

# 這些 server logger 必須統一向 root handler 傳遞，避免同一筆日誌重複輸出。
_MANAGED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "gunicorn.error",
    "gunicorn.access",
)

# 此鎖確保使用中的設定與已安裝 handler 永遠一起變更。
_state_lock = threading.RLock()
_active_config: LoggingConfig | None = None
_managed_handlers: tuple[logging.Handler, ...] = ()
_fork_registered = False


def configure_logging(
    filename: str | None = None,
    log_dir: str | os.PathLike[str] | None = None,
    *,
    level: str | int | None = None,
    retention_days: int | None = UNSET,  # pyright: ignore[reportArgumentType]
    max_file_size_mb: int | None = UNSET,  # pyright: ignore[reportArgumentType]
    timezone: str | None = None,
    console: bool = True,
    compression: Literal["gzip"] | None = UNSET,  # pyright: ignore[reportArgumentType]
) -> logging.Logger:
    """設定行程層級的 console 與多行程安全輪替檔案日誌。

    明確傳入的參數會覆蓋對應的 ``LOG_*`` 環境變數。未傳入保留期限、檔案大小或
    壓縮方式時，會讀取對應的環境變數；明確傳入 ``None`` 則會停用該功能。
    呼叫此函式前送出的日誌不會被保留。

    使用相同的最終設定重複呼叫時不會執行任何操作。若要套用不同設定，請先呼叫
    :func:`shutdown_logging`。

    回傳：
        已完成設定的標準函式庫 root logger。

    例外：
        ValueError：設定值無效。
        LoggingConfigurationError：無法初始化日誌目的地。
        LoggingAlreadyConfiguredError：目前已有不同的設定正在使用。
    """
    config = resolve_config(
        filename=filename,
        log_dir=log_dir,
        level=level,
        retention_days=retention_days,
        max_file_size_mb=max_file_size_mb,
        timezone=timezone,
        console=console,
        compression=compression,
    )

    with _state_lock:
        # 相同設定可安全重複執行；若要取代使用中的 handler，必須先明確關閉。
        if _active_config is not None:
            if _active_config == config:
                return logging.getLogger()
            raise LoggingAlreadyConfiguredError(
                "logging is already configured with different settings; "
                "call shutdown_logging() before reconfiguring"
            )

        _install_config(config)
        _register_at_fork()
        return logging.getLogger()


def shutdown_logging() -> None:
    """關閉並移除由 :func:`configure_logging` 安裝的 handler。"""
    global _active_config, _managed_handlers

    with _state_lock:
        root = logging.getLogger()
        for handler in _managed_handlers:
            root.removeHandler(handler)
            handler.close()
        _managed_handlers = ()
        _active_config = None
        root.setLevel(logging.WARNING)


def _install_config(config: LoggingConfig) -> None:
    global _active_config, _managed_handlers

    try:
        config.log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LoggingConfigurationError(
            f"cannot create or write to log directory '{config.log_dir}': {exc}"
        ) from exc
    if not config.log_dir.is_dir():
        raise LoggingConfigurationError(f"log path is not a directory: {config.log_dir}")
    _verify_directory_writable(config.log_dir)

    timezone = load_timezone(config.timezone_name)
    handlers: list[logging.Handler] = []
    # 先建立所有新 handler，再修改現有狀態，確保設定失敗時仍可安全復原。
    try:
        file_handler = DailyConcurrentFileHandler(config, timezone)
        file_handler.setLevel(config.level)
        file_handler.setFormatter(TimezoneFormatter(timezone))
        file_handler.cleanup_expired()
        handlers.append(file_handler)

        if config.console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(config.level)
            console_handler.setFormatter(
                TimezoneFormatter(timezone, color=stream_supports_color(sys.stderr))
            )
            handlers.append(console_handler)
    except Exception:
        for handler in handlers:
            handler.close()
        raise

    root = logging.getLogger()
    # 由 root 統一負責輸出；下方 framework logger 全部調整為向 root 傳遞。
    for handler in tuple(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(config.level)

    for logger_name in _MANAGED_LOGGERS:
        managed_logger = logging.getLogger(logger_name)
        for handler in tuple(managed_logger.handlers):
            managed_logger.removeHandler(handler)
            handler.close()
        managed_logger.setLevel(logging.NOTSET)
        managed_logger.propagate = True

    # 完整設定成功安裝後，才更新行程層級的狀態。
    _managed_handlers = tuple(handlers)
    _active_config = config
    logging.getLogger("common_tools.logging").info(
        "logging initialized file=%s retention_days=%s max_file_size_mb=%s "
        "timezone=%s compression=%s",
        config.active_file,
        config.retention_days,
        config.max_file_size_mb,
        config.timezone_name,
        config.compression,
    )


def _verify_directory_writable(directory: Path) -> None:
    """在啟動階段確認可寫入，避免之後遺失第一筆應用程式日誌。"""

    try:
        with tempfile.NamedTemporaryFile(prefix=".common-tools-write-test-", dir=directory):
            pass
    except OSError as exc:
        raise LoggingConfigurationError(
            f"cannot create or write to log directory '{directory}': {exc}"
        ) from exc


def _register_at_fork() -> None:
    """在支援 ``fork`` 的平台上，每個行程只註冊一次 child hook。"""

    global _fork_registered
    if _fork_registered or not hasattr(os, "register_at_fork"):
        return
    os.register_at_fork(after_in_child=_reinitialize_after_fork)
    _fork_registered = True


def _reinitialize_after_fork() -> None:
    global _state_lock
    # 從 parent 繼承的鎖與已開啟 handler 資源無法安全地在 child 中繼續使用。
    _state_lock = threading.RLock()
    config = _active_config
    if config is None:
        return
    try:
        _install_config(config)
    except Exception as exc:
        with suppress(Exception):
            print(f"common_tools.logging: cannot reinitialize after fork: {exc}", file=sys.stderr)
