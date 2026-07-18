# common-tools

[English](README.md) | **繁體中文**

供內部服務使用的 Python 3.12+ 基礎設施元件，提供應用程式設定、日誌、非同步
PostgreSQL／SQL Server 存取，以及 Redis 協調鎖。

## 安裝

正式環境應安裝不可變動的 Git tag，不要直接追蹤 `main`：

```bash
uv add "common-tools[postgres] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.3.1"
uv add "common-tools[sqlserver] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.3.1"
uv add "common-tools[redis] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.3.1"
uv add "common-tools[logging] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.3.1"
uv add "common-tools[all] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.3.1"
```

請依服務實際需要選擇額外依賴：

| 額外依賴 | 用途 |
|---|---|
| `postgres` | 非同步 PostgreSQL 存取 |
| `sqlserver` | 非同步 SQL Server 存取 |
| `redis` | Redis 協調鎖 |
| `logging` | 支援多行程輪替的檔案日誌 |
| `all` | 安裝以上所有功能 |

## 應用程式設定

`SettingsProvider` 在單一行程中持有一份共用設定實例；環境變數載入與資料驗證仍由應用程式
自行負責。應用程式可以安裝 `pydantic-settings`，並集中定義各項基礎設施設定：

```python
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from common_tools.settings import SettingsProvider


class LoggingSettings(BaseModel):
    filename: str = "billing-api"
    log_dir: str = "logs"
    level: str = "INFO"
    retention_days: int | None = 30
    max_file_size_mb: int | None = None
    timezone: str = "Asia/Taipei"


class PostgresSettings(BaseModel):
    url: SecretStr
    pool_size: int = 5
    max_overflow: int = 10


class RedisSettings(BaseModel):
    url: SecretStr
    lock_namespace: str = "billing"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BILLING_",
        env_nested_delimiter="__",
        frozen=True,
    )

    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    postgres: PostgresSettings
    redis: RedisSettings


_provider = SettingsProvider(Settings)

initialize_settings = _provider.initialize
get_settings = _provider.get
override_settings = _provider.override
```

例如，環境變數 `BILLING_POSTGRES__POOL_SIZE=10` 會轉換成
`settings.postgres.pool_size == 10`。`initialize_settings()` 呼叫 `Settings()` 時，
Pydantic 會負責環境變數載入、型別轉換與資料驗證。

請在應用程式進入點呼叫一次 `initialize_settings()`。重複初始化會拋出
`SettingsAlreadyInitializedError`；初始化前存取設定則會拋出
`SettingsNotInitializedError`。應用程式應在進入點讀取一次設定，並明確建立各項基礎設施資源：

```python
from redis.asyncio import Redis

from common_tools.database import AsyncDatabase, PostgresConfig
from common_tools.locking import RedisLockManager
from common_tools.logging import configure_logging


settings = initialize_settings()

configure_logging(
    filename=settings.logging.filename,
    log_dir=settings.logging.log_dir,
    level=settings.logging.level,
    retention_days=settings.logging.retention_days,
    max_file_size_mb=settings.logging.max_file_size_mb,
    timezone=settings.logging.timezone,
)

database = AsyncDatabase(
    PostgresConfig(
        url=settings.postgres.url.get_secret_value(),
        pool_size=settings.postgres.pool_size,
        max_overflow=settings.postgres.max_overflow,
    )
)

redis = Redis.from_url(settings.redis.url.get_secret_value())
locks = RedisLockManager(redis, namespace=settings.redis.lock_namespace)
```

`configure_logging`、`AsyncDatabase` 與 `RedisLockManager` 都不會呼叫 `get_settings()`，
也不依賴應用程式的設定結構。應用程式只需將各元件需要的最小設定或資源傳入即可。

測試時可使用 `with override_settings(test_settings): ...`。覆寫只在目前 context 內生效，
可正確巢狀使用，且並行的 async task 彼此隔離。`common-tools` 本身不依賴 Pydantic；任何
不需參數的設定 factory 都可以使用。

### 在 FastAPI 中初始化與使用

FastAPI 建議透過 [`lifespan` 參數](https://fastapi.tiangolo.com/advanced/events/) 管理應用程式的
啟動與關閉。請在 lifespan 中初始化設定與長期存活的基礎設施，將資源存放在 `app.state`，
再透過 FastAPI dependency 提供給 request handler：

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis

from common_tools.database import AsyncDatabase, PostgresConfig
from common_tools.locking import RedisLockManager
from common_tools.logging import configure_logging, shutdown_logging

from .config import Settings, get_settings, initialize_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = initialize_settings()
    configure_logging(
        filename=settings.logging.filename,
        log_dir=settings.logging.log_dir,
        level=settings.logging.level,
        retention_days=settings.logging.retention_days,
        max_file_size_mb=settings.logging.max_file_size_mb,
        timezone=settings.logging.timezone,
    )

    database = AsyncDatabase(
        PostgresConfig(
            url=settings.postgres.url.get_secret_value(),
            pool_size=settings.postgres.pool_size,
            max_overflow=settings.postgres.max_overflow,
        )
    )
    redis = Redis.from_url(settings.redis.url.get_secret_value())

    try:
        await database.start()
        await redis.ping()
        app.state.database = database
        app.state.locks = RedisLockManager(redis, namespace=settings.redis.lock_namespace)
        yield
    finally:
        await redis.aclose()
        await database.close()
        shutdown_logging()


app = FastAPI(lifespan=lifespan)
```

建議以具型別資訊的 dependency function 封裝對 `app.state` 的存取。因為 request handler
只會在 lifespan 初始化完成後執行，應用程式專屬設定可以直接透過 `get_settings()` 取得：

```python
def get_database(request: Request) -> AsyncDatabase:
    return request.app.state.database


def get_locks(request: Request) -> RedisLockManager:
    return request.app.state.locks


DatabaseDep = Annotated[AsyncDatabase, Depends(get_database)]
LocksDep = Annotated[RedisLockManager, Depends(get_locks)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@app.get("/runtime")
async def runtime_info(
    database: DatabaseDep,
    locks: LocksDep,
    settings: SettingsDep,
) -> dict[str, object]:
    return {
        "database_started": database.started,
        "lock_manager_ready": locks is not None,
        "log_level": settings.logging.level,
    }
```

不要在 module import 階段建立這些資源，也不要在每個 dependency 中呼叫
`initialize_settings()`。若測試需要完整執行 lifespan 的啟動與關閉流程，請以 context manager
方式使用 `TestClient(app)`。

## 應用程式日誌

安裝 `logging` 額外依賴後，請在應用程式進入點的前段設定一次 Python 標準函式庫日誌。
設定前就已建立的 logger 會在之後送出的紀錄套用新 handler；設定前已送出的紀錄不會被保留。

```python
import logging

from common_tools.logging import configure_logging

configure_logging(
    filename="billing-api",
    log_dir="logs",
    retention_days=30,
    max_file_size_mb=100,
)

logger = logging.getLogger(__name__)
logger.info("payment completed")
```

預設設定會將相同的固定文字格式寫入 UTF-8 檔案與 `stderr`。互動式終端機會顯示 ANSI
色彩；重新導向後的 console 輸出與檔案不會包含色彩。若未指定其他 IANA 時區，時間戳記、
每日輪替、封存日期與保留期限都會使用 `Asia/Taipei`。

```text
2026-07-15T14:32:08.481+08:00 INFO [billing.payment] [pid=1842 thread=MainThread] service.py:42 payment completed
```

目前使用中的日誌檔會在應用程式重啟與不同處理程序間維持固定檔名。輪替採延遲執行：午夜過後
的第一筆日誌才會觸發每日輪替。若設定 `max_file_size_mb`，目前日誌檔達到指定的軟性上限時
也會輪替。

```text
logs/billing-api.log
logs/billing-api.2026-07-15.001.log
logs/billing-api.2026-07-15.002.log
```

同一主機上的多個處理程序可以共用同一個目前日誌檔。handler 會以跨處理程序鎖保護寫入與
輪替，並在 `fork()` 後重新初始化資源。共享網路檔案系統與多主機部署不在可靠性保證範圍內；
這類部署請改由 console 日誌收集系統集中處理。

明確傳入的參數會覆蓋環境變數：

| 參數 | 環境變數 | 預設值 |
|---|---|---|
| `filename` | `LOG_FILENAME` | `app` |
| `log_dir` | `LOG_DIR` | `./logs` |
| `level` | `LOG_LEVEL` | `INFO` |
| `retention_days` | `LOG_RETENTION_DAYS` | `30` |
| `max_file_size_mb` | `LOG_MAX_FILE_SIZE_MB` | 停用 |
| `timezone` | `LOG_TIMEZONE` | `Asia/Taipei` |
| `compression` | `LOG_COMPRESSION` | 停用 |

即使對應的環境變數已設定，仍可明確傳入 `None` 以停用保留期限、檔案大小輪替或壓縮。
壓縮格式目前僅接受 `"gzip"`。日誌目錄會自動建立；設定無效或目錄無法寫入時，應用程式會在
啟動階段直接失敗。

`configure_logging()` 會取代 root、Uvicorn 與 Gunicorn 的 handler，避免日誌重複。
使用相同的最終設定再次呼叫時不會執行任何操作；若要變更設定，必須先明確呼叫
`shutdown_logging()`。

## 非同步 PostgreSQL 與 SQL Server

每個 `AsyncDatabase` 都只持有一個 SQLAlchemy engine。每個資料庫建立一個實例，在應用程式
啟動時啟用，並於關閉時釋放。本套件不會修改資料庫 session 的時區；若需要以 UTC 儲存，
應用程式必須自行寫入明確的 UTC 值。

```python
from common_tools.database import AsyncDatabase, PostgresConfig

database = AsyncDatabase(
    PostgresConfig(
        url="postgresql+asyncpg://user:password@localhost/app",
        pool_size=5,
        max_overflow=10,
    )
)

async with database:
    async with database.session() as session:
        # 不會隱含 commit，適合查詢或由呼叫端自行管理 transaction。
        result = await session.execute(...)

    async with database.transaction() as session:
        # 成功時 commit，發生例外時 rollback。
        session.add(...)
```

使用 framework 的應用程式可以在 lifespan hook 中呼叫 `await database.start()`，並於關閉時
呼叫可重複執行的 `await database.close()`。本套件不會保留全域資料庫實例、不會進行 tenant
routing、不會在背景自動重試，也不會協調跨資料庫 transaction。對已啟動的實例呼叫
`await database.check_connection()`，會執行 `SELECT 1` 檢查連線。

SQL Server 2019 以上版本使用獨立設定與 `mssql+aioodbc` dialect：

```python
from common_tools.database import AsyncDatabase, SqlServerConfig

erp_database = AsyncDatabase(
    SqlServerConfig(
        url=(
            "mssql+aioodbc://user:password@sql-server:1433/erp"
            "?driver=ODBC+Driver+18+for+SQL+Server"
            "&Encrypt=yes&TrustServerCertificate=no"
        )
    )
)
```

`SqlServerConfig` 支援不使用 DSN 的 SQL Server 身分驗證 URL，並要求 Microsoft ODBC
Driver 18。除了安裝 `sqlserver` Python 額外依賴外，也必須在應用程式映像檔中安裝系統層級
driver。Docker、降級啟動、重試、健康檢查與 CI 範例請參考
[SQL Server 與雙資料庫 FastAPI 使用指南](docs/sql-server.md)。

### 由應用程式管理 ORM metadata

每個使用本套件的服務都應擁有自己的 declarative base 與 Alembic migration 歷史。若應用程式
同時使用兩個資料庫，應分別定義 model base 與 migration 歷史。`common-tools` 只提供選用的
repr mixin 與穩定的 constraint 命名規則：

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from common_tools.database import NAMING_CONVENTION, ReprMixin


class AppBase(ReprMixin, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

本套件刻意不提供 runtime model 掃描與 `create_all()`；資料表結構應由各服務自己的 Alembic
migration 管理。

### Alembic 整合

先在服務的開發依賴中加入 Alembic，並建立 async migration 環境：

```bash
uv add --dev alembic
uv run alembic init -t async migrations
```

初始化後的主要結構如下：

```text
alembic.ini
migrations/
  env.py
  versions/
```

在 `migrations/env.py` 中明確匯入所有 model module，讓 SQLAlchemy 註冊完整的 table
metadata，再把服務自己的 `AppBase.metadata` 交給 Alembic。資料庫 URL 應從應用程式設定讀取，
不要將帳號密碼寫進 `alembic.ini`：

```python
from alembic import context

from my_service.config import initialize_settings
from my_service.models import account, invoice  # noqa: F401
from my_service.models.base import AppBase

settings = initialize_settings()

config = context.config
config.set_main_option(
    "sqlalchemy.url",
    settings.postgres.url.get_secret_value().replace("%", "%%"),
)
target_metadata = AppBase.metadata
```

`replace("%", "%%")` 可避免 URL 中的 `%` 被 Alembic／ConfigParser 當成插值語法。
保留 async template 產生的 `run_migrations_online()` 即可；不要掃描目錄來自動匯入 model。

開發時的基本流程：

```bash
# 根據 model 與目前資料庫 schema 的差異產生 migration
uv run alembic revision --autogenerate -m "add invoice status"

# 檢查產生的 migration 後，套用到最新版
uv run alembic upgrade head

# 確認 model 沒有尚未產生 migration 的變更，適合放進 CI
uv run alembic check
```

自動產生的 revision 只是候選內容，提交前仍需檢查欄位型別、破壞性操作、constraint 名稱與
資料搬移邏輯。正式部署時，應在啟動新版應用程式前，由獨立的 deployment step 執行
`alembic upgrade head`；不要讓每個 application replica 在啟動時各自執行 migration。

若同一服務同時使用 PostgreSQL 與 SQL Server，請為兩個資料庫建立完全獨立的 declarative
base、Alembic 設定與 revision 歷史，不要用同一份 autogenerate 結果套用到兩種 dialect：

```text
alembic.postgres.ini
alembic.sqlserver.ini
migrations/
  postgres/
    env.py
    versions/
  sqlserver/
    env.py
    versions/
```

兩套 migration 必須分別產生、檢查與部署：

```bash
uv run alembic -c alembic.postgres.ini revision --autogenerate -m "change primary schema"
uv run alembic -c alembic.sqlserver.ini revision --autogenerate -m "change ERP schema"

uv run alembic -c alembic.postgres.ini upgrade head
uv run alembic -c alembic.sqlserver.ini upgrade head
```

每個 `env.py` 只能匯入該資料庫的 model、指定對應的 base metadata，並讀取相符的資料庫 URL。

## Redis 協調鎖

`RedisLockManager` 使用由應用程式持有的 `redis.asyncio.Redis` client。鎖可以降低工作重複
執行的機率；業務正確性仍必須由資料庫 constraint、idempotency key 與 transaction 保護。

```python
from redis.asyncio import Redis

from common_tools.locking import RedisLockManager

redis = Redis.from_url("redis://localhost:6379/0")
locks = RedisLockManager(redis, namespace="prod:billing")

# 若鎖已由其他 worker 持有，就略過這次工作。
async with locks.try_acquire("daily-report", ttl=30, max_hold=600) as acquired:
    if acquired:
        await build_report()

# 最多等待指定時間；逾時會拋出 LockAcquisitionTimeout。
async with locks.acquire(
    "daily-report",
    ttl=30,
    max_hold=600,
    wait_timeout=10,
):
    await build_report()

await redis.aclose()
```

manager 會每隔 `ttl / 3` 自動續租持有中的 lease，並在續租與釋放時透過唯一 owner token
確認所有權。達到 `max_hold`、失去所有權或續租失敗時，受保護的 task 會被取消並拋出
`LockLostError`。第一次存取 Redis 就失敗時會拋出 `LockBackendUnavailable`，採 fail-closed
策略，不會繼續執行受保護的工作。

## 開發

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
uv run pytest -m integration
uv build
```

整合測試使用 Testcontainers，執行前必須先啟動 Docker daemon。

## 發佈

版本號由 Git tag 產生。重構前的程式碼保留為 `v0.1.0`；包含 breaking change 的重寫版本為
`v0.2.0`。完整流程請參考 [發佈程序](docs/releasing.md)。
