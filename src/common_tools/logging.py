"""Explicit, process-safe application logging configuration."""

from __future__ import annotations

import copy
import logging
import os
import re
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Final, Literal, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without the optional extra
    if exc.name not in {"concurrent_log_handler", "portalocker"}:
        raise
    raise ModuleNotFoundError(
        "File logging requires the optional dependency; install 'common-tools[logging]'"
    ) from exc

__all__ = [
    "DEFAULT_LOG_FORMAT",
    "LoggingAlreadyConfiguredError",
    "LoggingConfigurationError",
    "configure_logging",
    "shutdown_logging",
]

DEFAULT_LOG_FORMAT: Final = (
    "%(asctime)s %(levelname)s [%(name)s] [pid=%(process)d thread=%(threadName)s] "
    "%(filename)s:%(lineno)d %(message)s"
)

_COLOR_LOG_FORMAT: Final = (
    "\033[32m%(asctime)s\033[0m %(level_color)s%(levelname)s\033[0m "
    "[\033[34m%(name)s\033[0m] [pid=%(process)d thread=%(threadName)s] "
    "%(filename)s:%(lineno)d %(message)s"
)
_LEVEL_COLORS: Final = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[41;97m",
}
_MANAGED_LOGGERS: Final = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "gunicorn.error",
    "gunicorn.access",
)
_ARCHIVE_DATE_PATTERN: Final = r"(?P<day>\d{4}-\d{2}-\d{2})"


class LoggingConfigurationError(RuntimeError):
    """Raised when logging cannot be initialized safely."""


class LoggingAlreadyConfiguredError(LoggingConfigurationError):
    """Raised when a process attempts to replace an active logging configuration."""


class _UnsetType:
    def __repr__(self) -> str:
        return "<environment>"


_UNSET: Final = _UnsetType()


@dataclass(frozen=True, slots=True)
class _LoggingConfig:
    filename: str
    log_dir: Path
    level: int
    retention_days: int | None
    max_file_size_mb: int | None
    timezone_name: str
    console: bool
    compression: Literal["gzip"] | None

    @property
    def active_file(self) -> Path:
        return self.log_dir / f"{self.filename}.log"


class _TimezoneFormatter(logging.Formatter):
    def __init__(self, timezone: ZoneInfo, *, color: bool = False) -> None:
        super().__init__(_COLOR_LOG_FORMAT if color else DEFAULT_LOG_FORMAT)
        self._timezone = timezone
        self._color = color

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        del datefmt
        return datetime.fromtimestamp(record.created, self._timezone).isoformat(
            timespec="milliseconds"
        )

    def format(self, record: logging.LogRecord) -> str:
        if not self._color:
            return super().format(record)

        colored_record = copy.copy(record)
        colored_record.level_color = _LEVEL_COLORS.get(record.levelno, "")
        return super().format(colored_record)


class _DailyConcurrentFileHandler(ConcurrentTimedRotatingFileHandler):
    """Concurrent handler with timezone-aware daily archives and age retention."""

    def __init__(self, config: _LoggingConfig, timezone: ZoneInfo) -> None:
        self._archive_stem = config.filename
        self._timezone = timezone
        self._retention_days = config.retention_days
        self._archive_pattern = re.compile(
            rf"^{re.escape(config.filename)}\.{_ARCHIVE_DATE_PATTERN}\."
            r"(?P<segment>\d{3,})\.log(?:\.gz)?$"
        )
        self._error_lock = threading.Lock()
        self._last_error_report = 0.0
        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            filename=config.active_file,
            when="midnight",
            interval=1,
            # A positive value makes the base class call our age-based cleanup hook.
            backupCount=1,
            encoding="utf-8",
            errors="backslashreplace",
            maxBytes=(config.max_file_size_mb or 0) * 1024 * 1024,
            use_gzip=config.compression == "gzip",
            utc=True,
            keep_file_open=True,
        )

    def computeRollover(self, currentTime: int) -> int:
        current = datetime.fromtimestamp(currentTime, self._timezone)
        next_day = current.date() + timedelta(days=1)
        next_midnight = datetime.combine(next_day, datetime_time.min, self._timezone)
        return int(next_midnight.timestamp())

    def rotation_filename(self, default_name: str) -> str:
        del default_name
        archive_day = self._archive_day()
        next_segment = self._next_segment(archive_day)
        return str(
            Path(self.baseFilename).with_name(
                f"{self._archive_stem}.{archive_day.isoformat()}.{next_segment:03d}.log"
            )
        )

    def getFilesToDelete(self) -> list[str]:
        if self._retention_days is None:
            return []

        cutoff = datetime.now(self._timezone).date() - timedelta(days=self._retention_days - 1)
        return [str(path) for path, archive_day, _ in self._archives() if archive_day < cutoff]

    def cleanup_expired(self) -> None:
        try:
            self.clh._do_lock()  # pyright: ignore[reportPrivateUsage]
            for filename in self.getFilesToDelete():
                with suppress(FileNotFoundError):
                    Path(filename).unlink()
        finally:
            self.clh._do_unlock()  # pyright: ignore[reportPrivateUsage]

    def handleError(self, record: logging.LogRecord) -> None:
        del record
        now = time.monotonic()
        with self._error_lock:
            if now - self._last_error_report < 60:
                return
            self._last_error_report = now

        error = sys.exception()
        message = f"common_tools.logging: cannot write {self.baseFilename}"
        if error is not None:
            message = f"{message}: {error}"
        with suppress(Exception):
            print(message, file=sys.stderr)

    def _archive_day(self) -> date:
        now = self._get_current_time()
        if now >= self.rolloverAt:
            return datetime.fromtimestamp(self.rolloverAt, self._timezone).date() - timedelta(
                days=1
            )
        return datetime.fromtimestamp(now, self._timezone).date()

    def _next_segment(self, archive_day: date) -> int:
        segments = [
            segment
            for _, candidate_day, segment in self._archives()
            if candidate_day == archive_day
        ]
        return max(segments, default=0) + 1

    def _archives(self) -> list[tuple[Path, date, int]]:
        archives: list[tuple[Path, date, int]] = []
        directory = Path(self.baseFilename).parent
        try:
            entries = directory.iterdir()
        except FileNotFoundError:
            return archives

        for path in entries:
            match = self._archive_pattern.fullmatch(path.name)
            if match is None or path.is_symlink():
                continue
            try:
                archive_day = date.fromisoformat(match.group("day"))
                segment = int(match.group("segment"))
            except ValueError:
                continue
            archives.append((path, archive_day, segment))
        return archives


_state_lock = threading.RLock()
_active_config: _LoggingConfig | None = None
_managed_handlers: tuple[logging.Handler, ...] = ()
_fork_registered = False


def configure_logging(
    filename: str | None = None,
    log_dir: str | os.PathLike[str] | None = None,
    *,
    level: str | int | None = None,
    retention_days: int | None = _UNSET,  # pyright: ignore[reportArgumentType]
    max_file_size_mb: int | None = _UNSET,  # pyright: ignore[reportArgumentType]
    timezone: str | None = None,
    console: bool = True,
    compression: Literal["gzip"] | None = _UNSET,  # pyright: ignore[reportArgumentType]
) -> logging.Logger:
    """Configure process-wide console and process-safe rotating file logging.

    Explicit arguments override their ``LOG_*`` environment variables. Omitting
    retention, size, or compression reads the corresponding environment variable;
    explicitly passing ``None`` disables that feature. Records emitted before this
    function is called are not retained.

    Repeating an identical effective configuration is a no-op. Call
    :func:`shutdown_logging` before applying different settings.

    Returns:
        The configured standard-library root logger.

    Raises:
        ValueError: A setting is invalid.
        LoggingConfigurationError: The log destination cannot be initialized.
        LoggingAlreadyConfiguredError: Different settings are already active.
    """
    config = _resolve_config(
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
    """Close and remove handlers installed by :func:`configure_logging`."""
    global _active_config, _managed_handlers

    with _state_lock:
        root = logging.getLogger()
        for handler in _managed_handlers:
            root.removeHandler(handler)
            handler.close()
        _managed_handlers = ()
        _active_config = None
        root.setLevel(logging.WARNING)


def _resolve_config(
    *,
    filename: str | None,
    log_dir: str | os.PathLike[str] | None,
    level: str | int | None,
    retention_days: int | None | _UnsetType,
    max_file_size_mb: int | None | _UnsetType,
    timezone: str | None,
    console: bool,
    compression: Literal["gzip"] | None | _UnsetType,
) -> _LoggingConfig:
    resolved_filename = filename if filename is not None else os.getenv("LOG_FILENAME", "app")
    _validate_filename(resolved_filename)

    raw_log_dir = log_dir if log_dir is not None else os.getenv("LOG_DIR", "logs")
    if not os.fspath(raw_log_dir):
        raise ValueError("log_dir must not be empty")
    resolved_log_dir = Path(raw_log_dir).expanduser().resolve()

    resolved_level = _resolve_level(level if level is not None else os.getenv("LOG_LEVEL", "INFO"))
    resolved_retention = _resolve_optional_positive_int(
        retention_days,
        environment="LOG_RETENTION_DAYS",
        default=30,
        field="retention_days",
    )
    resolved_max_size = _resolve_optional_positive_int(
        max_file_size_mb,
        environment="LOG_MAX_FILE_SIZE_MB",
        default=None,
        field="max_file_size_mb",
    )
    resolved_timezone = (
        timezone if timezone is not None else os.getenv("LOG_TIMEZONE", "Asia/Taipei")
    )
    _load_timezone(resolved_timezone)
    resolved_compression = _resolve_compression(compression)

    return _LoggingConfig(
        filename=resolved_filename,
        log_dir=resolved_log_dir,
        level=resolved_level,
        retention_days=resolved_retention,
        max_file_size_mb=resolved_max_size,
        timezone_name=resolved_timezone,
        console=console,
        compression=resolved_compression,
    )


def _resolve_level(value: str | int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid log level: {value}")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"invalid log level: {value}")
        return value

    normalized = value.strip().upper()
    resolved = logging.getLevelNamesMapping().get(normalized)
    if resolved is None:
        raise ValueError(f"invalid log level: {value}")
    return resolved


def _resolve_optional_positive_int(
    value: int | None | _UnsetType,
    *,
    environment: str,
    default: int | None,
    field: str,
) -> int | None:
    resolved: int | None
    if isinstance(value, _UnsetType):
        raw_environment = os.getenv(environment)
        if raw_environment is None:
            resolved = default
        elif raw_environment.strip().lower() == "none":
            resolved = None
        else:
            try:
                resolved = int(raw_environment)
            except ValueError as exc:
                raise ValueError(f"{environment} must be a positive integer or 'none'") from exc
    else:
        resolved = value

    if isinstance(resolved, bool) or (resolved is not None and resolved <= 0):
        raise ValueError(f"{field} must be a positive integer or None")
    return resolved


def _resolve_compression(
    value: Literal["gzip"] | None | _UnsetType,
) -> Literal["gzip"] | None:
    resolved = os.getenv("LOG_COMPRESSION") if isinstance(value, _UnsetType) else value

    if resolved is None:
        return None
    if resolved.strip().lower() == "none":
        return None
    if resolved.strip().lower() != "gzip":
        raise ValueError("compression must be 'gzip' or None")
    return "gzip"


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or not filename.strip()
        or filename != filename.strip()
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or filename.lower().endswith(".log")
        or any(ord(character) < 32 for character in filename)
    ):
        raise ValueError("filename must be a safe file stem without a path or '.log' suffix")


def _load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc


def _install_config(config: _LoggingConfig) -> None:
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

    timezone = _load_timezone(config.timezone_name)
    handlers: list[logging.Handler] = []
    try:
        file_handler = _DailyConcurrentFileHandler(config, timezone)
        file_handler.setLevel(config.level)
        file_handler.setFormatter(_TimezoneFormatter(timezone))
        file_handler.cleanup_expired()
        handlers.append(file_handler)

        if config.console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(config.level)
            console_handler.setFormatter(
                _TimezoneFormatter(timezone, color=_stream_supports_color(sys.stderr))
            )
            handlers.append(console_handler)
    except Exception:
        for handler in handlers:
            handler.close()
        raise

    root = logging.getLogger()
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

    _managed_handlers = tuple(handlers)
    _active_config = config
    logging.getLogger(__name__).info(
        "logging initialized file=%s retention_days=%s max_file_size_mb=%s "
        "timezone=%s compression=%s",
        config.active_file,
        config.retention_days,
        config.max_file_size_mb,
        config.timezone_name,
        config.compression,
    )


def _verify_directory_writable(directory: Path) -> None:
    try:
        with tempfile.NamedTemporaryFile(prefix=".common-tools-write-test-", dir=directory):
            pass
    except OSError as exc:
        raise LoggingConfigurationError(
            f"cannot create or write to log directory '{directory}': {exc}"
        ) from exc


def _stream_supports_color(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False


def _register_at_fork() -> None:
    global _fork_registered
    if _fork_registered or not hasattr(os, "register_at_fork"):
        return
    os.register_at_fork(after_in_child=_reinitialize_after_fork)
    _fork_registered = True


def _reinitialize_after_fork() -> None:
    global _state_lock
    _state_lock = threading.RLock()
    config = _active_config
    if config is None:
        return
    try:
        _install_config(config)
    except Exception as exc:
        with suppress(Exception):
            print(f"common_tools.logging: cannot reinitialize after fork: {exc}", file=sys.stderr)
