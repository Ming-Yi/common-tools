import gzip
import io
import logging
import multiprocessing
import os
import re
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from common_tools.logging import (
    LoggingAlreadyConfiguredError,
    LoggingConfigurationError,
    configure_logging,
    shutdown_logging,
)

_ENVIRONMENT_VARIABLES = (
    "LOG_FILENAME",
    "LOG_DIR",
    "LOG_LEVEL",
    "LOG_RETENTION_DAYS",
    "LOG_MAX_FILE_SIZE_MB",
    "LOG_TIMEZONE",
    "LOG_COMPRESSION",
)


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _write_logs_in_process(
    log_dir: str,
    process_number: int,
    count: int,
    max_file_size_mb: int | None = None,
    payload_size: int = 0,
) -> None:
    from common_tools.logging import configure_logging

    configure_logging(
        filename="workers",
        log_dir=log_dir,
        max_file_size_mb=max_file_size_mb,
        console=False,
    )
    logger = logging.getLogger(f"worker.{process_number}")
    payload = "x" * payload_size
    for index in range(count):
        logger.info("message process=%d index=%d payload=%s", process_number, index, payload)


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    root = logging.getLogger()
    original_handlers = tuple(root.handlers)
    original_level = root.level
    managed_loggers = ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error")
    original_managed_state = {
        name: (
            tuple(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in managed_loggers
    }
    for name in _ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    yield

    shutdown_logging()
    for handler in tuple(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)
    for name, (handlers, level, propagate) in original_managed_state.items():
        logger = logging.getLogger(name)
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate


def test_defaults_create_a_file_and_use_the_fixed_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    configure_logging(console=False)
    logging.getLogger("billing.payment").info("payment completed")

    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "logging initialized file=" in content
    assert re.search(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+08:00 INFO "
        r"\[billing\.payment\] \[pid=\d+ thread=MainThread\] test_logging\.py:\d+ "
        r"payment completed",
        content,
    )


def test_exception_includes_its_traceback(tmp_path: Path) -> None:
    configure_logging(filename="app", log_dir=tmp_path, console=False)
    logger = logging.getLogger("billing")

    try:
        raise RuntimeError("payment exploded")
    except RuntimeError:
        logger.exception("payment failed")

    content = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "payment failed" in content
    assert "Traceback (most recent call last):" in content
    assert "RuntimeError: payment exploded" in content


def test_console_uses_color_only_for_a_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = _TtyBuffer()
    monkeypatch.setattr(sys, "stderr", terminal)

    configure_logging(filename="app", log_dir=tmp_path)
    logging.getLogger("billing").warning("low balance")

    assert "\033[33mWARNING\033[0m" in terminal.getvalue()
    assert "\033[" not in (tmp_path / "app.log").read_text(encoding="utf-8")


def test_explicit_arguments_override_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_dir = tmp_path / "environment"
    explicit_dir = tmp_path / "explicit"
    monkeypatch.setenv("LOG_FILENAME", "environment")
    monkeypatch.setenv("LOG_DIR", str(environment_dir))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    configure_logging(filename="explicit", log_dir=explicit_dir, level="INFO", console=False)
    logging.getLogger("app").info("written")

    assert (explicit_dir / "explicit.log").exists()
    assert "written" in (explicit_dir / "explicit.log").read_text(encoding="utf-8")
    assert not environment_dir.exists()


def test_explicit_none_disables_environment_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taipei = ZoneInfo("Asia/Taipei")
    old_day = datetime.now(taipei).date() - timedelta(days=100)
    archive = tmp_path / f"app.{old_day.isoformat()}.001.log"
    archive.write_text("old", encoding="utf-8")
    monkeypatch.setenv("LOG_RETENTION_DAYS", "1")

    configure_logging(filename="app", log_dir=tmp_path, retention_days=None, console=False)

    assert archive.exists()


def test_startup_removes_archives_older_than_calendar_retention(tmp_path: Path) -> None:
    taipei = ZoneInfo("Asia/Taipei")
    today = datetime.now(taipei).date()
    expired = tmp_path / f"app.{today - timedelta(days=2)}.001.log"
    retained = tmp_path / f"app.{today - timedelta(days=1)}.001.log"
    unrelated = tmp_path / f"other.{today - timedelta(days=20)}.001.log"
    for path in (expired, retained, unrelated):
        path.write_text(path.name, encoding="utf-8")

    configure_logging(filename="app", log_dir=tmp_path, retention_days=2, console=False)

    assert not expired.exists()
    assert retained.exists()
    assert unrelated.exists()


def test_size_rotation_uses_date_and_increasing_segments(tmp_path: Path) -> None:
    configure_logging(
        filename="app",
        log_dir=tmp_path,
        max_file_size_mb=1,
        console=False,
    )
    logger = logging.getLogger("app")
    logger.info("x" * (1024 * 1024))
    logger.info("trigger first rollover")
    logger.info("y" * (1024 * 1024))
    logger.info("trigger second rollover")

    day = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    assert (tmp_path / f"app.{day}.001.log").exists()
    assert (tmp_path / f"app.{day}.002.log").exists()
    assert "trigger second rollover" in (tmp_path / "app.log").read_text(encoding="utf-8")


def test_gzip_compresses_rotated_segments(tmp_path: Path) -> None:
    configure_logging(
        filename="app",
        log_dir=tmp_path,
        max_file_size_mb=1,
        compression="gzip",
        console=False,
    )
    logger = logging.getLogger("app")
    logger.info("x" * (1024 * 1024))
    logger.info("trigger rollover")

    day = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    archive = tmp_path / f"app.{day}.001.log.gz"
    assert archive.exists()
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        assert "xxxxxxxx" in stream.read()


def test_forced_daily_rollover_names_the_previous_taipei_day(tmp_path: Path) -> None:
    configure_logging(filename="app", log_dir=tmp_path, console=False)
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if hasattr(handler, "write_rollover_time")
    )
    forced_rollover = int(time.time()) - 1
    handler.clh._do_lock()  # type: ignore[attr-defined]  # pyright: ignore[reportPrivateUsage]
    try:
        handler.rolloverAt = forced_rollover  # type: ignore[attr-defined]
        handler.write_rollover_time()  # type: ignore[attr-defined]
    finally:
        handler.clh._do_unlock()  # type: ignore[attr-defined]  # pyright: ignore[reportPrivateUsage]

    logging.getLogger("app").info("new day")

    archive_day = datetime.fromtimestamp(
        forced_rollover, ZoneInfo("Asia/Taipei")
    ).date() - timedelta(days=1)
    assert (tmp_path / f"app.{archive_day}.001.log").exists()
    assert "new day" in (tmp_path / "app.log").read_text(encoding="utf-8")


def test_configuration_is_idempotent_but_rejects_changes(tmp_path: Path) -> None:
    first = configure_logging(filename="app", log_dir=tmp_path, console=False)
    second = configure_logging(filename="app", log_dir=tmp_path, console=False)

    assert first is second
    with pytest.raises(LoggingAlreadyConfiguredError, match="different settings"):
        configure_logging(filename="other", log_dir=tmp_path, console=False)

    shutdown_logging()
    configure_logging(filename="other", log_dir=tmp_path, console=False)
    assert (tmp_path / "other.log").exists()


@pytest.mark.parametrize(
    "filename", ["", " ", ".", "..", "../app", "logs/app", "app.log", "app\nname"]
)
def test_filename_must_be_a_safe_stem(tmp_path: Path, filename: str) -> None:
    with pytest.raises(ValueError, match="safe file stem"):
        configure_logging(filename=filename, log_dir=tmp_path, console=False)


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("retention_days", 0),
        ("retention_days", -1),
        ("max_file_size_mb", 0),
        ("max_file_size_mb", -1),
        ("level", "VERBOSE"),
        ("timezone", "Asia/Taipe"),
        ("compression", "zip"),
    ],
)
def test_invalid_configuration_is_rejected(tmp_path: Path, keyword: str, value: object) -> None:
    arguments: dict[str, object] = {
        "filename": "app",
        "log_dir": tmp_path,
        "console": False,
        keyword: value,
    }
    with pytest.raises(ValueError):
        configure_logging(**arguments)  # type: ignore[arg-type]


def test_log_path_that_is_a_file_fails_configuration(tmp_path: Path) -> None:
    path = tmp_path / "not-a-directory"
    path.write_text("content", encoding="utf-8")

    with pytest.raises(LoggingConfigurationError):
        configure_logging(filename="app", log_dir=path, console=False)


def test_existing_root_and_server_handlers_are_replaced(tmp_path: Path) -> None:
    root_handler = logging.StreamHandler(io.StringIO())
    server_handler = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(root_handler)
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.addHandler(server_handler)
    uvicorn_logger.propagate = False

    configure_logging(filename="app", log_dir=tmp_path, console=False)
    uvicorn_logger.info("server started")

    assert root_handler not in logging.getLogger().handlers
    assert server_handler not in uvicorn_logger.handlers
    assert uvicorn_logger.propagate
    assert "server started" in (tmp_path / "app.log").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="spawn process test is flaky on Windows CI")
def test_multiple_processes_write_complete_records_to_one_file(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    process_count = 4
    message_count = 50
    processes = [
        context.Process(
            target=_write_logs_in_process,
            args=(str(tmp_path), process_number, message_count),
        )
        for process_number in range(process_count)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    content = (tmp_path / "workers.log").read_text(encoding="utf-8")
    messages = [line for line in content.splitlines() if "message process=" in line]
    assert len(messages) == process_count * message_count
    assert all(" index=" in line for line in messages)


@pytest.mark.skipif(sys.platform == "win32", reason="spawn process test is flaky on Windows CI")
def test_multiple_processes_can_rotate_one_file_without_losing_records(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    process_count = 3
    message_count = 25
    processes = [
        context.Process(
            target=_write_logs_in_process,
            args=(str(tmp_path), process_number, message_count, 1, 20_000),
        )
        for process_number in range(process_count)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    contents = "".join(
        path.read_text(encoding="utf-8") for path in sorted(tmp_path.glob("workers*.log"))
    )
    markers = set(re.findall(r"message process=\d+ index=\d+", contents))
    expected = {
        f"message process={process_number} index={index}"
        for process_number in range(process_count)
        for index in range(message_count)
    }
    assert markers == expected
    assert list(tmp_path.glob("workers.*.001.log"))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_forked_child_reinitializes_its_file_handler(tmp_path: Path) -> None:
    configure_logging(filename="forked", log_dir=tmp_path, console=False)

    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - assertions run in the parent
        try:
            logging.getLogger("child").info("written by child")
            shutdown_logging()
            os._exit(0)
        except BaseException:
            os._exit(1)

    _, status = os.waitpid(child_pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    logging.getLogger("parent").info("written by parent")

    content = (tmp_path / "forked.log").read_text(encoding="utf-8")
    assert "written by child" in content
    assert "written by parent" in content
