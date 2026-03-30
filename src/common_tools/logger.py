"""
日誌管理模組

此模組提供基於 Loguru 的日誌管理功能，支援控制台和檔案輸出，
使用單例模式確保全域日誌配置的一致性。
"""
import logging as _logging
import os
import sys
import threading

from loguru import logger

from .base_classes import SingletonMeta, StaticUtils

__all__ = ["Logging"]


class Logger(metaclass=SingletonMeta):
    """
    日誌管理器類別，輸出日誌到檔案和控制台。

    使用單例模式確保整個應用程式中只有一個日誌實例，
    提供統一的日誌配置和管理功能。
    """

    def __init__(
            self,
            filename: str,
            level: str = os.environ.get("LOG_LEVEL", "INFO"),
            log_dir: str = os.environ.get("LOG_DIR", "logs"),
            packages: list[str] | None = None,
    ):
        """
        初始化日誌管理器。

        配置控制台和檔案輸出，設定日誌格式、輪轉規則等。

        Args:
            filename: 日誌檔案名稱（不包含日期和副檔名）
            level: 日誌等級（預設：從環境變數 LOG_LEVEL 讀取，若無則使用 "INFO"）
            packages: 需要套用應用程式 level 的第三方套件前綴列表（預設：None，全部維持原本 level）
            log_dir: 日誌目錄路徑（預設：從環境變數 LOG_DIR 讀取，若無則使用 "logs"）
        """
        # 確保日誌目錄存在
        os.makedirs(log_dir, exist_ok=True)

        if packages is None:
            packages = ["uvicorn"]

        # 攔截標準 logging 模組的日誌，將其重新導向到 Loguru
        _logging.basicConfig(handlers=[InterceptHandler(packages=packages)], level=level, force=True)

        # 初始化 Loguru logger
        self.logger = logger
        self.logger.remove()

        def console_format(record):
            if record["extra"].get("intercepted"):
                src = "[<cyan>{extra[log_name]}</cyan>]"
            else:
                src = "[<cyan>{name}</cyan>:<cyan>{function}</cyan>:<yellow>{line}</yellow>]"
            return (
                "<green>{time:YYYYMMDD HH:mm:ss}</green> | "
                "[<magenta>{process.name}</magenta>:<yellow>{thread.name}</yellow>] "
                f"{src} "
                "[<level>{level}</level>] "
                "<level>{message}</level>\n"
            )

        def file_format(record):
            if record["extra"].get("intercepted"):
                src = "[{extra[log_name]}]"
            else:
                src = "[{name}:{function}:{line}]"
            return (
                "{time:YYYY-MM-DD HH:mm:ss} [{process.name}:{thread.name}] "
                f"{src} {{message}}\n"
            )

        # 控制台輸出
        self.logger.add(
            sys.stdout,
            level=level,
            format=console_format,
        )

        # 日誌寫入檔案
        self.logger.add(
            f"{log_dir}/{filename}_{{time:YYYY-MM-DD}}.log",
            level=level,
            format=file_format,
            encoding="utf-8",
            retention="30 days",
            backtrace=True,
            diagnose=True,
            enqueue=True,
            rotation="00:00",
            compression="zip",
        )

    def get_logger(self):
        return self.logger


class InterceptHandler(_logging.Handler):
    """
    攔截標準 logging 模組的日誌記錄，並將其重新導向到 Loguru 系統。
    """

    def __init__(self, packages: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.packages = packages

    def emit(self, record: _logging.LogRecord) -> None:  # pragma: no cover
        if not any(record.name.startswith(pkg) for pkg in self.packages):
            # 如果日誌記錄不屬於指定的套件前綴，則不進行攔截，直接使用原本的 logging 處理
            return

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.bind(
            intercepted=True,
            log_name=record.name
        ).opt(
            exception=record.exc_info
        ).log(level, record.getMessage())


class Logging(StaticUtils):
    _logger = None
    _lock = threading.Lock()

    @classmethod
    def _get_logger(cls):
        if cls._logger is None:
            with cls._lock:
                if cls._logger is None:
                    filename = os.environ.get("LOG_FILENAME", "app")
                    log_dir = os.environ.get("LOG_DIR", "logs")
                    cls._logger = Logger(filename, log_dir=log_dir).get_logger()
        return cls._logger

    @staticmethod
    def initialize(
            filename: str = None,
            packages: list[str] | None = None,
            log_dir: str = None,
    ) -> None:
        """
        明確初始化日誌系統。

        Args:
            filename: 日誌檔案名稱（預設：從環境變數 LOG_FILENAME 讀取，若無則使用 "app"）
            packages: 需要套用應用程式 level 的第三方套件前綴列表（預設：["uvicorn"]）
            log_dir: 日誌目錄路徑（預設：從環境變數 LOG_DIR 讀取，若無則使用 "logs"）
        """
        with Logging._lock:
            if Logging._logger is None:
                if filename is None:
                    filename = os.environ.get("LOG_FILENAME", "app")
                if log_dir is None:
                    log_dir = os.environ.get("LOG_DIR", "logs")
                Logging._logger = Logger(filename, packages=packages, log_dir=log_dir).get_logger()

    @staticmethod
    def info(msg, *args, **kwargs):
        Logging._get_logger().opt(depth=1).info(msg, *args, **kwargs)

    @staticmethod
    def error(msg, *args, **kwargs):
        Logging._get_logger().opt(depth=1).error(msg, *args, **kwargs)

    @staticmethod
    def warning(msg, *args, **kwargs):
        Logging._get_logger().opt(depth=1).warning(msg, *args, **kwargs)

    @staticmethod
    def debug(msg, *args, **kwargs):
        Logging._get_logger().opt(depth=1).debug(msg, *args, **kwargs)

    @staticmethod
    def exception(msg, *args, **kwargs):
        Logging._get_logger().opt(depth=1).exception(msg, *args, **kwargs)
