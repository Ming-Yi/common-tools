from dataclasses import dataclass, field

from sqlalchemy.engine import make_url

__all__ = ["PostgresConfig"]


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """Validated configuration for an async PostgreSQL connection pool."""

    url: str = field(repr=False)
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: float = 30.0
    pool_recycle: int = 1800
    pool_pre_ping: bool = True

    def __post_init__(self) -> None:
        if make_url(self.url).drivername != "postgresql+asyncpg":
            raise ValueError("url must use the postgresql+asyncpg driver")
        if self.pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        if self.max_overflow < 0:
            raise ValueError("max_overflow must not be negative")
        if self.pool_timeout <= 0:
            raise ValueError("pool_timeout must be greater than zero")
        if self.pool_recycle <= 0:
            raise ValueError("pool_recycle must be greater than zero")
