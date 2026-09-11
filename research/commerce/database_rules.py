"""SQLAlchemy's explicit database-rule task; snekql baseline remains unpatched."""

from typing import Any

from sqlalchemy import CheckConstraint, Integer, Text, create_mock_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def ddl(backend: str) -> list[str]:
    """Declare a literal server default and a positive-quantity CHECK."""

    class Base(DeclarativeBase):
        pass

    class RuleOrder(Base):
        __tablename__ = "rule_orders"
        __table_args__ = (CheckConstraint("quantity > 0", name="ck_quantity_positive"),)
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        quantity: Mapped[int] = mapped_column(Integer)
        status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))

    statements: list[str] = []

    def capture(statement: Any, *_args: Any, **_kwargs: Any) -> None:
        statements.append(str(statement.compile(dialect=engine.dialect)).strip())

    engine = create_mock_engine(
        "sqlite://" if backend == "sqlite" else "mariadb+pymysql://", capture
    )
    Base.metadata.create_all(engine, checkfirst=False)
    return statements
