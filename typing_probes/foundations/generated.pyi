"""Throwaway generated typing facade. Regenerate with foundations.generate."""

# Preserve schema field names and explanatory research docstrings.
# ruff: noqa: A002, PYI021

from typing_probes.foundations.core import Column, Deleting, Query, Updating, Write
from typing_probes.foundations.schema import Account

class AccountTable:
    age: Column[Account, int]
    id: Column[Account, int]
    name: Column[Account, str]
    nickname: Column[Account, str | None]
    def select(self) -> Query[Account, Account]: ...
    def insert(
        self, *, age: int, id: int = ..., name: str, nickname: str | None = ...
    ) -> Write[Account]: ...
    def update(self) -> Updating[Account]: ...
    def delete(self) -> Deleting[Account]: ...

accounts: AccountTable
