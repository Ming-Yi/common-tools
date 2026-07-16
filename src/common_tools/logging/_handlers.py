"""支援多行程安全的檔案寫入、輪替、壓縮與保留期限。"""

# ruff: noqa: RUF003

import logging
import re
import sys
import threading
import time
from contextlib import suppress
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

# 匯入此 module 時即檢查 logging 額外依賴，讓啟動失敗時能提供明確的處理方式。
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
except ModuleNotFoundError as exc:  # pragma: no cover - 未安裝額外依賴時測試
    if exc.name not in {"concurrent_log_handler", "portalocker"}:
        raise
    raise ModuleNotFoundError(
        "File logging requires the optional dependency; install 'common-tools[logging]'"
    ) from exc

from ._config import LoggingConfig

__all__ = ["DailyConcurrentFileHandler"]

_ARCHIVE_DATE_PATTERN = r"(?P<day>\d{4}-\d{2}-\d{2})"


class DailyConcurrentFileHandler(ConcurrentTimedRotatingFileHandler):
    """支援指定時區每日封存與保存期限的多行程 handler。"""

    def __init__(self, config: LoggingConfig, timezone: ZoneInfo) -> None:
        self._archive_stem = config.filename
        self._timezone = timezone
        self._retention_days = config.retention_days
        # 只比對此 handler 擁有的封存檔，並包含選用的 gzip 輸出。
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
            # 正值會讓基底類別呼叫依日期清理檔案的 hook。
            backupCount=1,
            encoding="utf-8",
            errors="backslashreplace",
            maxBytes=(config.max_file_size_mb or 0) * 1024 * 1024,
            use_gzip=config.compression == "gzip",
            utc=True,
            keep_file_open=True,
        )

    def computeRollover(self, currentTime: int) -> int:
        # 上游 handler 內部使用 UTC，但輪替政策必須依指定時區的日曆日期計算。
        current = datetime.fromtimestamp(currentTime, self._timezone)
        next_day = current.date() + timedelta(days=1)
        next_midnight = datetime.combine(next_day, datetime_time.min, self._timezone)
        return int(next_midnight.timestamp())

    def rotation_filename(self, default_name: str) -> str:
        del default_name
        archive_day = self._archive_day()
        # 每日與檔案大小輪替共用遞增編號，避免封存檔名互相衝突。
        next_segment = self._next_segment(archive_day)
        return str(
            Path(self.baseFilename).with_name(
                f"{self._archive_stem}.{archive_day.isoformat()}.{next_segment:03d}.log"
            )
        )

    def getFilesToDelete(self) -> list[str]:
        if self._retention_days is None:
            return []

        # 保留期限以日曆日含首尾計算，因此今天的封存檔算第一天。
        cutoff = datetime.now(self._timezone).date() - timedelta(days=self._retention_days - 1)
        return [str(path) for path, archive_day, _ in self._archives() if archive_day < cutoff]

    def cleanup_expired(self) -> None:
        # 使用 handler 的跨行程鎖，避免清理與其他行程的輪替互相競爭。
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
        # 寫入目的地故障時限制回報頻率，避免形成無限的 stderr 錯誤迴圈。
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
            # 超過輪替時間但尚未輪替時，目前檔案仍屬於前一個日曆日。
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
            # 依保存期限刪除檔案時絕不跟隨符號連結。
            if match is None or path.is_symlink():
                continue
            try:
                archive_day = date.fromisoformat(match.group("day"))
                segment = int(match.group("segment"))
            except ValueError:
                continue
            archives.append((path, archive_day, segment))
        return archives
