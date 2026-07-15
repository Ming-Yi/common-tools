"""Server-side Lua scripts for atomic, ownership-checked lock operations."""

__all__ = ["REDIS_RELEASE_LOCK_SCRIPT", "REDIS_RENEW_LOCK_SCRIPT"]

REDIS_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

REDIS_RENEW_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""
