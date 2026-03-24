# common-tools

Internal utility library. Requires Python 3.14+.

## Installation

From internal git server:

```bash
pip install git+https://github.com/Ming-Yi/common-tools.git
```

Install a specific version/tag:

```bash
pip install git+https://github.com/Ming-Yi/common-tools.git
```

## Modules

### Logging

基於 [Loguru](https://github.com/Delgan/loguru) 的日誌管理，支援控制台與檔案輸出，使用單例模式確保全域一致性。

```python
from common_tools import Logging

# 明確初始化（建議在應用程式入口呼叫）
Logging.initialize(filename="myapp", log_dir="/var/log/myapp", packages=["uvicorn"])

# 直接使用（未初始化時會自動使用預設值）
Logging.info("Hello")
Logging.warning("Watch out")
Logging.error("Something went wrong")
Logging.debug("Debug message")
Logging.exception("Unhandled exception")
```

**環境變數**

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `LOG_LEVEL` | 日誌等級 | `INFO` |
| `LOG_DIR` | 日誌目錄路徑 | `logs` |
| `LOG_FILENAME` | 日誌檔案名稱 | `app` |

---

### Database

基於 [SQLAlchemy](https://www.sqlalchemy.org/) 的資料庫管理，支援同步與非同步操作。

#### 同步

```python
from common_tools.database import Database, Base, db_session, create_all_tables

# 初始化
Database().initialise("postgresql://user:pass@host/db")

# 建立所有資料表（自動載入指定資料夾下的 Model）
create_all_tables("/app/models")

# Session 管理
with db_session() as session:
    session.add(obj)
```

#### 非同步

```python
from common_tools.database import AsyncDatabase, async_db_session, async_create_all_tables

# 初始化
await AsyncDatabase().initialise("postgresql+asyncpg://user:pass@host/db")

# 建立所有資料表
await async_create_all_tables("/app/models")

# Session 管理
async with async_db_session() as session:
    session.add(obj)
```

#### ORM Model

```python
from common_tools.database import Base

class User(Base):
    __tablename__ = "users"
    # ...
```

#### PostgreSQL Advisory Lock

```python
from common_tools.database import pg_advisory_lock, async_pg_advisory_lock

# 同步
with pg_advisory_lock(lock_id=1234) as acquired:
    if acquired:
        ...

# 非同步
async with async_pg_advisory_lock(lock_id=1234) as acquired:
    if acquired:
        ...
```

> `pg_advisory_lock` 與 `async_pg_advisory_lock` 僅支援 PostgreSQL。

---

## Development

```bash
git clone http://your-git-server/common-tools.git
cd common-tools
pip install -e ".[dev]"
pytest
```
