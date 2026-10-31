"""Shared named-query declarations; no fixtures, runtime or database state.

These exact declarations are shared inputs, not a canonical schema for unrelated
query tests. Backend-specific models and fixture lifetimes remain at their owners.
"""

from typing import ClassVar

from pydantic import BaseModel

from snekql import sqlite


class Person[S = sqlite.Pending](sqlite.Model[S]):
    """A table independent from its named result contract."""

    __row_type__: ClassVar[sqlite.ReadType[Person[sqlite.Row]]]

    id: Person.Col[int] = sqlite.Integer(primary_key=True)
    name: Person.Col[str] = sqlite.Text()


class PersonSummary(BaseModel):
    """An application result contract, not a table declaration."""

    id: int
    name: str


class OptionalPersonSummary(BaseModel):
    """A result field that admits an unmatched joined row."""

    id: int
    name: str | None


class PeerRole:
    """A nominal role for a second occurrence of Person."""


class WidePerson(BaseModel):
    """Nine independently named values exceed the positional overload ceiling."""

    first: int
    second: int
    third: int
    fourth: int
    fifth: int
    sixth: int
    seventh: int
    eighth: int
    ninth: int
