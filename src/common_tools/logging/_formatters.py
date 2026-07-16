"""提供含時區資訊的文字與彩色日誌格式。"""

# ruff: noqa: RUF003

import copy
import logging
from datetime import datetime
from typing import Final, TextIO
from zoneinfo import ZoneInfo

__all__ = ["DEFAULT_LOG_FORMAT", "TimezoneFormatter", "stream_supports_color"]

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


class TimezoneFormatter(logging.Formatter):
    """使用應用程式指定時區的 ISO 時間戳格式化日誌。"""

    def __init__(self, timezone: ZoneInfo, *, color: bool = False) -> None:
        super().__init__(_COLOR_LOG_FORMAT if color else DEFAULT_LOG_FORMAT)
        self._timezone = timezone
        self._color = color

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        # 固定使用 ISO 格式，確保檔案與 console 的時間戳完全一致。
        del datefmt
        return datetime.fromtimestamp(record.created, self._timezone).isoformat(
            timespec="milliseconds"
        )

    def format(self, record: logging.LogRecord) -> str:
        if not self._color:
            return super().format(record)

        # 複製 record，避免額外加入的 level_color 欄位影響共用此 record 的其他 handler。
        colored_record = copy.copy(record)
        colored_record.level_color = _LEVEL_COLORS.get(record.levelno, "")
        return super().format(colored_record)


def stream_supports_color(stream: TextIO) -> bool:
    """判斷 stream 是否能安全接收 ANSI 色彩控制碼。"""

    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False
