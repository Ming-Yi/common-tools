import asyncio

import pytest

from common_tools.settings import (
    SettingsAlreadyInitializedError,
    SettingsNotInitializedError,
    SettingsProvider,
)


def test_get_rejects_access_before_initialization() -> None:
    provider = SettingsProvider(lambda: "production")

    with pytest.raises(SettingsNotInitializedError, match="not initialized"):
        provider.get()


def test_initialize_creates_and_returns_settings_once() -> None:
    created: list[str] = []

    def create_settings() -> str:
        created.append("production")
        return created[-1]

    provider = SettingsProvider(create_settings)

    settings = provider.initialize()

    assert settings == "production"
    assert provider.get() is settings
    assert created == ["production"]

    with pytest.raises(SettingsAlreadyInitializedError, match="already initialized"):
        provider.initialize()

    assert created == ["production"]


def test_failed_initialization_can_be_retried() -> None:
    attempts = 0

    def create_settings() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("invalid environment")
        return "production"

    provider = SettingsProvider(create_settings)

    with pytest.raises(ValueError, match="invalid environment"):
        provider.initialize()

    assert provider.initialize() == "production"


def test_override_does_not_require_process_settings() -> None:
    provider = SettingsProvider(lambda: "production")

    with provider.override("test") as settings:
        assert settings == "test"
        assert provider.get() == "test"

    with pytest.raises(SettingsNotInitializedError):
        provider.get()


def test_nested_overrides_restore_previous_values() -> None:
    provider = SettingsProvider(lambda: "production")
    provider.initialize()

    with provider.override("outer"):
        assert provider.get() == "outer"

        with provider.override("inner"):
            assert provider.get() == "inner"

        assert provider.get() == "outer"

    assert provider.get() == "production"


@pytest.mark.asyncio
async def test_overrides_are_isolated_between_async_tasks() -> None:
    provider = SettingsProvider(lambda: "production")
    provider.initialize()
    both_ready = asyncio.Event()
    release = asyncio.Event()
    ready_count = 0

    async def read_override(value: str) -> str:
        nonlocal ready_count
        with provider.override(value):
            ready_count += 1
            if ready_count == 2:
                both_ready.set()
            await release.wait()
            return provider.get()

    first = asyncio.create_task(read_override("first"))
    second = asyncio.create_task(read_override("second"))

    await both_ready.wait()
    assert provider.get() == "production"
    release.set()

    assert await asyncio.gather(first, second) == ["first", "second"]
    assert provider.get() == "production"
