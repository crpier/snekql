"""Research-only state declarations over native SQLite models and queries."""

from annotationlib import Format, ForwardRef, get_annotations
from collections.abc import Callable
from types import GenericAlias
from typing import (
    Any,
    ClassVar,
    TypeVar,
    cast,
    evaluate_forward_ref,
    get_args,
    get_origin,
)

from snekql import sqlite as native
from snekql.model import _MODEL_BASE_MARKER
from snekql.sqlite.model import ModelMeta as NativeModelMeta


class ModelMeta(NativeModelMeta):
    def __new__(
        mcls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: object,
    ) -> Any:
        model = super().__new__(mcls, name, bases, namespace, **kwargs)
        if namespace.get("__snekql_framework_base__") is _MODEL_BASE_MARKER:
            return model
        hint = get_annotations(model, format=Format.FORWARDREF).get("__read_type__")
        if get_origin(hint) is not ClassVar:
            raise native.ModelDeclarationError("Declare a ClassVar ReadType witness")
        witness = get_args(hint)[0]
        if get_origin(witness) is not ReadType:
            raise native.ModelDeclarationError("Declare a ReadType witness")
        target = get_args(witness)[0]
        if isinstance(target, ForwardRef):
            target = evaluate_forward_ref(target, owner=model, locals={name: model})
        if get_origin(target) is not model or get_args(target) != (native.Fetched,):
            raise native.ModelDeclarationError(
                "ReadType must name this model's Fetched specialization"
            )
        type.__setattr__(model, "__read_type__", ReadType())
        return model


class _StateAlias(GenericAlias):
    def __call__(self, **values: object) -> Any:
        model: Any = self.__origin__
        phase = self.__args__[0]
        if phase is native.Fetched:
            columns = model.__snekql_columns__
            if set(values) != set(columns) or any(
                value is native.PENDING_GENERATION for value in values.values()
            ):
                raise native.ModelValidationError(
                    "Fetched construction requires every column value"
                )
        instance = model(**values)
        if phase is native.Fetched:
            if any(
                getattr(instance, name) is native.PENDING_GENERATION
                for name in model.__snekql_columns__
            ):
                raise native.ModelValidationError(
                    "Fetched constructor left a generated value unavailable"
                )
            object.__getattribute__(instance, "__dict__")["_snekql_state"] = "Fetched"
        return instance


class Model[State](native.Model[State, Any], metaclass=ModelMeta):
    """Hide the old result parameter while experiments supply concrete evidence."""

    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER

    def __init__(self, **values: object) -> None:
        super().__init__(**values)

    @classmethod
    def __class_getitem__(cls, state: object) -> Any:
        if isinstance(state, tuple) and len(state) == 1:
            state = state[0]
        if state is native.Pending or state is native.Fetched:
            return _StateAlias(cls, state)
        if isinstance(state, TypeVar) or state is Any:
            return super().__class_getitem__(state)
        raise native.ModelDeclarationError("Use Pending or Fetched as the model state")


class ReadType[Result]:
    """An explicit result witness expressed as an ordinary deferred annotation."""

    def __get__(
        self, instance: object, owner: type[object]
    ) -> Callable[[], type[Result]]:
        def read_type() -> type[Result]:
            # The metaclass validates the declared specialization before publication.
            return cast("type[Result]", cast("Any", owner)[native.Fetched])

        return read_type
