"""Generated historical query declarations; regenerate after editing the route."""

from typing import ClassVar

from snekql import sqlite


class Historical[S = sqlite.Pending](sqlite.Model[S]):
    """Query-only historical contract, not a schema ownership declaration."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[Historical[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(nullable=False)
    is_admin: sqlite.Col[bool] = sqlite.Integer(nullable=False)
    role: sqlite.Col[str | None] = sqlite.Text(nullable=True)


CONTRACT_DIGEST = "fba20206731abb719669b5a902f9e2e2312c87867ccd33d1e5d39df996c83e4a"
