from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common_tools.database import ReprMixin


class AppBase(DeclarativeBase):
    pass


class Widget(ReprMixin, AppBase):
    __tablename__ = "widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]


def test_repr_mixin_formats_mapped_columns() -> None:
    assert repr(Widget(id=7, label="ready")) == "Widget(id=7, label='ready')"
