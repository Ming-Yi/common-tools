from collections.abc import Iterator

import pytest
from sqlalchemy.engine import make_url
from testcontainers.mssql import SqlServerContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def sql_server_url() -> Iterator[str]:
    with SqlServerContainer(
        "mcr.microsoft.com/mssql/server:2019-latest",
        dialect="mssql+aioodbc",
    ) as sql_server:
        url = make_url(sql_server.get_connection_url()).update_query_dict(
            {
                "driver": "ODBC Driver 18 for SQL Server",
                "Encrypt": "yes",
                "TrustServerCertificate": "yes",
            }
        )
        yield url.render_as_string(hide_password=False)


@pytest.fixture
def redis_url() -> Iterator[str]:
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    redis = (
        DockerContainer("redis:8-alpine")
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
