"""Generated historical query declarations; regenerate after editing the route."""

from typing import ClassVar

from snekql import mariadb


class Historical[S = mariadb.Pending](mariadb.Model[S]):
    """Query-only historical contract, not a schema ownership declaration."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[Historical[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(nullable=False)
    is_admin: mariadb.Col[bool] = mariadb.Integer(nullable=False)
    role: mariadb.Col[str | None] = mariadb.Text(nullable=True)


CONTRACT_DIGEST = "34b777ec336321361f36c59b588e642468762e42d0bbc78fb39f0ef3fdf64ea7"
