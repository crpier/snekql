"""Synchronous, once-only declaration binding with terminal failure states."""

from collections.abc import Callable
from threading import RLock
from typing import Literal, cast

from snekql.errors import ModelDeclarationError

_BINDING_LOCK = RLock()
"""Serialize first use across dependent bindings without a model registry."""


class _OnceBinding[T]:
    """Memoize a binding, rejecting reentry and never retrying user callbacks."""

    def __init__(self, label: str, build: Callable[[], T]) -> None:
        self._label: str = label
        self._build: Callable[[], T] = build
        self._state: Literal["unresolved", "resolving", "resolved", "failed"] = (
            "unresolved"
        )
        self._value: T | None = None
        self._failure: BaseException | None = None

    def get(self, *, allow_reentry: bool = False) -> T | None:
        """Only storage dependency traversal may reuse an in-progress model."""
        with _BINDING_LOCK:
            if self._state == "resolving":
                if allow_reentry:
                    return None
                msg = f"cyclic declaration binding: {self._label}"
                raise ModelDeclarationError(msg)
            if self._state == "unresolved":
                self._state = "resolving"
                try:
                    self._value = self._build()
                except Exception as error:
                    self._failure = error
                    self._state = "failed"
                else:
                    self._state = "resolved"
                finally:
                    # Preserve cancellation/interrupt propagation while preventing retry.
                    if self._state == "resolving":
                        self._state = "failed"
                        self._failure = ModelDeclarationError(
                            f"declaration binding interrupted: {self._label}",
                        )
            if self._state == "failed":
                msg = (
                    str(self._failure)
                    if isinstance(self._failure, ModelDeclarationError)
                    else f"cannot bind declaration: {self._label}"
                )
                raise ModelDeclarationError(msg) from self._failure
            # The resolved state distinguishes a legitimate None from missing data.
            return cast("T", self._value)
