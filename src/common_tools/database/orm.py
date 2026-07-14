from collections.abc import Iterator
from typing import Any, ClassVar, cast

from sqlalchemy import inspect
from sqlalchemy.orm import Mapper

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class ReprMixin:
    """Formats mapped columns without traversing ORM relationships."""

    __repr_include__: ClassVar[tuple[str, ...] | None] = None

    def _repr_items(self) -> Iterator[tuple[str, Any]]:
        mapper = cast(Mapper[Any], inspect(type(self)))
        keys = [attribute.key for attribute in mapper.column_attrs]
        if self.__repr_include__ is not None:
            keys = [key for key in keys if key in self.__repr_include__]
        for key in keys:
            yield key, getattr(self, key, None)

    def __repr__(self) -> str:
        values = ", ".join(f"{key}={value!r}" for key, value in self._repr_items())
        return f"{type(self).__name__}({values})"
