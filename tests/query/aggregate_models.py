"""MariaDB input declarations for public aggregate SQL inspection.

The SQLite models in the aggregate test modules keep their separate identities.
This module supplies no database fixture or observed execution result.
"""

from typing import ClassVar

from snekql import mariadb


class MariaUser[S = mariadb.Pending](mariadb.Model[S]):
    """Native table compiled under the same SQL name as the SQLite inputs."""

    __tablename__ = "user"
    __row_type__: ClassVar[mariadb.ReadType[MariaUser[mariadb.Row]]]

    id: MariaUser.Col[int] = mariadb.Integer(primary_key=True)
    country: MariaUser.Col[str] = mariadb.Text(nullable=False)
