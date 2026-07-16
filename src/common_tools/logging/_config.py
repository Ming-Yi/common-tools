"""解析環境變數並驗證日誌設定。"""

# ruff: noqa: RUF002, RUF003

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["UNSET", "LoggingConfig", "load_timezone", "resolve_config"]


class _UnsetType:
    """區分未傳入參數與明確使用 ``None`` 停用功能。"""

    def __repr__(self) -> str:
        return "<environment>"


UNSET: Final = _UnsetType()


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """單次日誌安裝所使用的標準化且已驗證設定。"""

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


def resolve_config(
    *,
    filename: str | None,
    log_dir: str | os.PathLike[str] | None,
    level: str | int | None,
    retention_days: int | None | _UnsetType,
    max_file_size_mb: int | None | _UnsetType,
    timezone: str | None,
    console: bool,
    compression: Literal["gzip"] | None | _UnsetType,
) -> LoggingConfig:
    """依序以明確參數、環境變數與內建預設值解析設定。"""

    resolved_filename = filename if filename is not None else os.getenv("LOG_FILENAME", "app")
    _validate_filename(resolved_filename)

    raw_log_dir = log_dir if log_dir is not None else os.getenv("LOG_DIR", "logs")
    if not os.fspath(raw_log_dir):
        raise ValueError("log_dir must not be empty")
    # 轉為絕對標準路徑，讓工作目錄改變前後的重複設定仍能正確比較。
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
    load_timezone(resolved_timezone)
    resolved_compression = _resolve_compression(compression)

    return LoggingConfig(
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
        # 只有未傳入的值才讀取環境變數；明確傳入 None 一律代表停用功能。
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
    # handler 會自行加上「.log」，呼叫端只能提供不含路徑跳脫內容的檔名主體。
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


def load_timezone(name: str) -> ZoneInfo:
    """載入 IANA 時區，並將查詢失敗統一轉成 ``ValueError``。"""

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc
