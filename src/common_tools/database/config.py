from dataclasses import dataclass, field

from sqlalchemy.engine import make_url

__all__ = ["PostgresConfig", "SqlServerConfig"]


def _validate_pool_settings(
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: float,
    pool_recycle: int,
) -> None:
    if pool_size < 1:
        raise ValueError("pool_size must be at least 1")
    if max_overflow < 0:
        raise ValueError("max_overflow must not be negative")
    if pool_timeout <= 0:
        raise ValueError("pool_timeout must be greater than zero")
    if pool_recycle <= 0:
        raise ValueError("pool_recycle must be greater than zero")


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
        _validate_pool_settings(
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
        )


@dataclass(frozen=True, slots=True)
class SqlServerConfig:
    """Validated configuration for an async SQL Server connection pool."""

    url: str = field(repr=False)
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: float = 30.0
    pool_recycle: int = 1800
    pool_pre_ping: bool = True

    def __post_init__(self) -> None:
        url = make_url(self.url)
        if url.drivername != "mssql+aioodbc":
            raise ValueError("url must use the mssql+aioodbc driver")
        if url.query.get("driver") != "ODBC Driver 18 for SQL Server":
            raise ValueError("url must specify driver=ODBC Driver 18 for SQL Server")
        _validate_pool_settings(
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
        )
