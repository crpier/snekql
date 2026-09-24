"""Observe current model callback timing without changing snekql."""
from collections.abc import Callable
from snekql import sqlite


def local_name_timing() -> None:
    """A local model name is unavailable while declaration hooks execute."""
    callbacks: list[Callable[[], object]] = []
    observations: list[str] = []

    class Account[S=sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        callbacks.append(lambda: Account.key)

        @classmethod
        def __indexes__(cls) -> list[object]:
            try:
                callbacks[0]()
            except NameError:
                observations.append("name unavailable during declaration")
            try:
                cls.key.index = True
            except sqlite.FrozenModelError:
                observations.append("column already frozen during declaration hook")
            return []

    assert observations == [
        "name unavailable during declaration",
        "column already frozen during declaration hook",
    ]
    assert callbacks[0]() is Account.key
    print("local class: lookup fails in hook, succeeds after definition; metadata frozen")


def redefinition_timing() -> None:
    """A rebound name can silently refer to the old model during a new declaration."""
    observed: list[object] = []
    callbacks: list[Callable[[], object]] = []

    class Account[S=sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    previous = Account

    class Account[S=sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        callbacks.append(lambda: Account.key)

        @classmethod
        def __indexes__(cls) -> list[object]:
            observed.append(callbacks[0]())
            return []

    assert observed == [previous.key]
    assert callbacks[0]() is Account.key
    print("redefined class: hook sees old model; post-definition lookup sees new model")


local_name_timing()
redefinition_timing()
