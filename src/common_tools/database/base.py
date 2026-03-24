from typing import Any, ClassVar, Iterable, Tuple

from sqlalchemy.inspection import inspect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Single declarative base for all ORM models (SQLAlchemy 2.0 typed ORM).
    - Provides safe __repr__ (columns only; avoids relationships/lazy loads)
    - Provides overridable init_data hook
    """

    # 可選：若你想控制 __repr__ 印哪些欄位，可在子類覆寫
    __repr_include__: ClassVar[Tuple[str, ...] | None] = None  # e.g. ("id", "email")

    def iter_kv_for_repr(self) -> Iterable[tuple[str, Any]]:
        """
        Yield (column_name, value) pairs for repr.
        Columns only to avoid relationship lazy-load or noisy internal attrs.
        """
        mapper = inspect(self.__class__)
        col_names = [col.key for col in mapper.columns]

        include = getattr(self.__class__, "__repr_include__", None)
        if include:
            col_names = [c for c in col_names if c in include]

        for k in col_names:
            # 讀取 column 屬性一般不會觸發 relationship lazy-load；
            # 若欄位本身是 deferred，讀取仍可能觸發載入（這屬正常行為）。
            yield k, getattr(self, k, None)

    def __repr__(self) -> str:
        params = ", ".join(f"{k}={v!r}" for k, v in self.iter_kv_for_repr())
        return f"{self.__class__.__name__}({params})"

    @classmethod
    def init_data(cls, session) -> None:
        """
        Seed/initialize default data hook.
        Subclasses may override. Default: no-op.
        """
        return


class DatabaseConnectionError(Exception):
    def __init__(self, message):
        super().__init__(message)
