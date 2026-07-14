import asyncio
from contextlib import suppress

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from common_tools.locking import (
    LockAcquisitionTimeout,
    LockBackendUnavailable,
    LockLostError,
    RedisLockManager,
)


def test_lock_manager_requires_a_namespace() -> None:
    with pytest.raises(ValueError, match="namespace"):
        RedisLockManager(object(), namespace="")  # type: ignore[arg-type]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_try_acquire_skips_work_when_lock_is_held(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        async with (
            manager.try_acquire("daily-report", ttl=0.5, max_hold=2) as first,
            manager.try_acquire("daily-report", ttl=0.5, max_hold=2) as second,
        ):
            result = first, second
    finally:
        await client.aclose()

    assert result == (True, False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_held_lock_is_renewed_before_its_ttl_expires(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        async with manager.try_acquire("long-job", ttl=0.15, max_hold=1) as first:
            await asyncio.sleep(0.35)
            async with manager.try_acquire("long-job", ttl=0.15, max_hold=1) as second:
                result = first, second
    finally:
        await client.aclose()

    assert result == (True, False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_renew_stops_work_at_max_hold(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        with pytest.raises(LockLostError, match="maximum hold"):
            async with manager.try_acquire("bounded-job", ttl=0.15, max_hold=0.3) as acquired:
                assert acquired
                await asyncio.sleep(1)
    finally:
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_acquire_stops_waiting_at_its_deadline(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        async with manager.try_acquire("contended-job", ttl=0.2, max_hold=1) as acquired:
            assert acquired
            with pytest.raises(LockAcquisitionTimeout):
                async with manager.acquire(
                    "contended-job",
                    ttl=0.2,
                    max_hold=1,
                    wait_timeout=0.15,
                ):
                    pass
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_backend_failure_is_reported_explicitly() -> None:
    client = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.05)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        with pytest.raises(LockBackendUnavailable):
            async with manager.try_acquire("daily-report", ttl=0.2, max_hold=1):
                pass
    finally:
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_renewal_failure_cancels_protected_work(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        manager = RedisLockManager(client, namespace="test:billing")
        with pytest.raises(LockLostError):
            async with manager.try_acquire("interrupted-job", ttl=0.15, max_hold=2) as acquired:
                assert acquired
                with suppress(RedisError):
                    await client.shutdown(nosave=True, now=True, force=True)
                await asyncio.sleep(1)
    finally:
        await client.aclose()
