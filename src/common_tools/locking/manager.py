import asyncio
import logging
import math
import random
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .exceptions import LockAcquisitionTimeout, LockBackendUnavailable, LockLostError
from .scripts import REDIS_RELEASE_LOCK_SCRIPT, REDIS_RENEW_LOCK_SCRIPT

__all__ = ["RedisLockManager"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LeaseState:
    error: LockLostError | None = None
    cause: BaseException | None = None


class RedisLockManager:
    """Coordinates work with namespaced, lease-based Redis locks."""

    def __init__(self, redis: Redis, *, namespace: str) -> None:
        namespace = namespace.strip().strip(":")
        if not namespace:
            raise ValueError("namespace must not be empty")
        self._redis = redis
        self._prefix = f"common-tools:lock:{namespace}"
        self._release_lock = redis.register_script(REDIS_RELEASE_LOCK_SCRIPT)
        self._renew_lock = redis.register_script(REDIS_RENEW_LOCK_SCRIPT)

    @asynccontextmanager
    async def try_acquire(
            self,
            key: str,
            *,
            ttl: float,
            max_hold: float,
    ) -> AsyncGenerator[bool]:
        if not key:
            raise ValueError("key must not be empty")
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl must be greater than zero")
        if not math.isfinite(max_hold) or max_hold < ttl:
            raise ValueError("max_hold must be greater than or equal to ttl")

        full_key = f"{self._prefix}:{key}"
        token = secrets.token_urlsafe(32)
        ttl_ms = max(1, round(ttl * 1000))
        try:
            acquired = bool(await self._redis.set(full_key, token, nx=True, px=ttl_ms))
        except RedisError as error:
            raise LockBackendUnavailable("Redis unavailable while acquiring lock") from error
        if not acquired:
            yield False
            return

        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("lock acquisition requires an asyncio task")
        state = _LeaseState()
        renewal_task = asyncio.create_task(
            self._renew(full_key, token, ttl, ttl_ms, max_hold, owner, state)
        )
        body_error: BaseException | None = None
        try:
            yield True
        except asyncio.CancelledError as cancelled:
            if state.error is not None:
                body_error = state.error
                raise body_error from (state.cause or cancelled)
            body_error = cancelled
            raise
        except BaseException as error:
            body_error = error
            raise
        finally:
            renewal_task.cancel()
            with suppress(asyncio.CancelledError):
                await renewal_task
            try:
                await self._release_lock(keys=[full_key], args=[token])
            except RedisError as error:
                if body_error is None and state.error is None:
                    message = "Redis unavailable while releasing lock"
                    raise LockBackendUnavailable(message) from error
                logger.warning("Redis unavailable while releasing lock %r", key)

    @asynccontextmanager
    async def acquire(
            self,
            key: str,
            *,
            ttl: float,
            max_hold: float,
            wait_timeout: float,
    ) -> AsyncGenerator[None]:
        if not math.isfinite(wait_timeout) or wait_timeout <= 0:
            raise ValueError("wait_timeout must be greater than zero")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_timeout
        retry_delay = min(0.05, wait_timeout)
        while True:
            async with self.try_acquire(key, ttl=ttl, max_hold=max_hold) as acquired:
                if acquired:
                    yield
                    return

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise LockAcquisitionTimeout(f"timed out waiting for lock {key!r}")
            delay = min(remaining, random.uniform(retry_delay / 2, retry_delay))
            await asyncio.sleep(delay)
            retry_delay = min(retry_delay * 2, 0.5)

    async def _renew(
            self,
            key: str,
            token: str,
            ttl: float,
            ttl_ms: int,
            max_hold: float,
            owner: asyncio.Task[object],
            state: _LeaseState,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_hold
        while True:
            await asyncio.sleep(min(ttl / 3, max(0, deadline - loop.time())))
            if loop.time() >= deadline:
                state.error = LockLostError("lock reached its maximum hold time")
                owner.cancel()
                return
            try:
                renewed = await self._renew_lock(keys=[key], args=[token, ttl_ms])
            except RedisError as error:
                state.error = LockLostError("Redis unavailable during lock renewal")
                state.cause = error
                owner.cancel()
                return
            if not renewed:
                state.error = LockLostError("lock ownership was lost during renewal")
                owner.cancel()
                return
