# SQL Server and dual-database FastAPI usage

`common-tools` supports SQL Server 2019 and later through SQLAlchemy's `mssql+aioodbc` dialect.
Install the `sqlserver` extra in Python and Microsoft ODBC Driver 18 in the application container.
Only DSN-less SQL Server username/password URLs are supported.

## Application image

The ODBC driver is a system dependency. Install it in the FastAPI image; do not install SQL Server
itself in that image. This example targets Debian 12 (`bookworm`):

```dockerfile
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && curl --fail --show-error --location \
        --output /tmp/packages-microsoft-prod.deb \
        https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install --yes --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Install the application and common-tools[postgres,sqlserver] here.
```

Use the Microsoft repository path matching the image distribution and version. Production URLs
should use `Encrypt=yes&TrustServerCertificate=no` with a certificate trusted by the container.
`TrustServerCertificate=yes` is suitable only for controlled local and CI containers.

## Two independent databases

Name database resources after their business roles. Each instance owns its engine, pool, sessions,
and transactions. A transaction on one instance never commits or rolls back work on the other.

The application owns availability policy and retry tasks. The example below lets FastAPI start
while either database is unavailable, serializes lifecycle operations through one supervisor per
instance, and returns HTTP 503 from routes whose database is unavailable:

```python
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status

from common_tools.database import (
    AsyncDatabase,
    DatabaseConnectionError,
    PostgresConfig,
    SqlServerConfig,
)

from .config import initialize_settings


@dataclass(slots=True)
class DatabaseResource:
    database: AsyncDatabase
    available: bool = False


async def supervise(resource: DatabaseResource, retry_seconds: float = 10) -> None:
    while True:
        try:
            if not resource.database.started:
                await resource.database.start()
            await resource.database.check_connection()
            resource.available = True
        except DatabaseConnectionError:
            resource.available = False
            await resource.database.close()
        await asyncio.sleep(retry_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = initialize_settings()
    primary = DatabaseResource(
        AsyncDatabase(PostgresConfig(url=settings.postgres_url.get_secret_value()))
    )
    erp = DatabaseResource(
        AsyncDatabase(SqlServerConfig(url=settings.sql_server_url.get_secret_value()))
    )
    app.state.primary_database = primary
    app.state.erp_database = erp

    supervisors = [
        asyncio.create_task(supervise(primary), name="primary-database-supervisor"),
        asyncio.create_task(supervise(erp), name="erp-database-supervisor"),
    ]
    try:
        yield
    finally:
        for task in supervisors:
            task.cancel()
        await asyncio.gather(*supervisors, return_exceptions=True)
        await erp.database.close()
        await primary.database.close()


app = FastAPI(lifespan=lifespan)


def require_primary_database(request: Request) -> AsyncDatabase:
    resource: DatabaseResource = request.app.state.primary_database
    if not resource.available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "primary database unavailable")
    return resource.database


def require_erp_database(request: Request) -> AsyncDatabase:
    resource: DatabaseResource = request.app.state.erp_database
    if not resource.available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ERP database unavailable")
    return resource.database


PrimaryDatabase = Annotated[AsyncDatabase, Depends(require_primary_database)]
ErpDatabase = Annotated[AsyncDatabase, Depends(require_erp_database)]
```

The availability flag belongs to the application. `started` only means an engine exists; it is not
a live-health guarantee. A request must create its own session from the injected database and must
not share an `AsyncSession` with another request or task.

## CI integration database

SQL Server Developer Edition is free for development and CI, but not licensed for production.
Accept its EULA explicitly and pin the tested major version:

```yaml
services:
  sql-server:
    image: mcr.microsoft.com/mssql/server:2019-latest
    env:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "1Secure*Password1"
    ports:
      - 1433:1433
```

The CI runner executing Python also needs ODBC Driver 18. Integration connection URLs may use
`Encrypt=yes&TrustServerCertificate=yes` for the container's self-signed certificate.

Do not use SQL Server Developer Edition as the production database. SQL Server production edition
and licensing choices belong to the deploying service.
