"""Static contracts shared by throwaway model-definition experiments."""

# Explicit invariance keeps owner/value widening out of negative controls.
# ruff: noqa: PYI021, UP046

from collections.abc import Callable
from typing import Generic, Self, TypeVar, dataclass_transform, overload

_Owner = TypeVar("_Owner")
_Value = TypeVar("_Value")

class Omitted: ...

OMIT: Omitted

class Column(Generic[_Owner, _Value]):
    def eq(self, value: _Value) -> Predicate[_Owner]: ...
    def to(self, value: _Value) -> Assignment[_Owner]: ...

class Predicate(Generic[_Owner]): ...
class Assignment(Generic[_Owner]): ...
class Query[Row]: ...

class Write[Row]:
    def with_(self, assignment: Assignment[Row]) -> Write[Row]: ...

class Field[Value]:
    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> Column[Owner, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __set__(self, instance: object, value: Value) -> None: ...

def field[Value](*, default: Value = ..., init: bool = True) -> Field[Value]: ...

@dataclass_transform(field_specifiers=(field,), kw_only_default=True)
class Model:
    @classmethod
    def create[**Parameters, Row](
        cls: Callable[Parameters, Row],
        *args: Parameters.args,
        **kwargs: Parameters.kwargs,
    ) -> Write[Row]: ...

def insert[**Parameters, Row](
    model: Callable[Parameters, Row],
    *args: Parameters.args,
    **kwargs: Parameters.kwargs,
) -> Write[Row]: ...
def select[Row](model: type[Row]) -> Query[Row]: ...

@dataclass_transform(field_specifiers=(field,), kw_only_default=True)
class ReturningNew:
    def __new__(cls, *args: object, **kwargs: object) -> Write[Self]: ...

@dataclass_transform(field_specifiers=(field,), kw_only_default=True)
class ReturningMeta(type):
    def __call__[Row](
        cls: type[Row], *args: object, **kwargs: object
    ) -> Write[Row]: ...

class Generated[Value](Field[Value]):
    def __set__(self, instance: object, value: Value | Omitted) -> None: ...

def generated[Value](
    *, default: Omitted = ..., init: bool = True
) -> Generated[Value]: ...

@dataclass_transform(field_specifiers=(field, generated), kw_only_default=True)
class GeneratedModel(Model): ...

@dataclass_transform(
    field_specifiers=(field,), kw_only_default=True, frozen_default=True
)
class FrozenModel: ...

class Read[Input]:
    @classmethod
    def insert(cls, value: Input) -> Write[Self]: ...

class BoundInsert[**Parameters, Row]:
    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Write[Row]: ...

class InsertUsing[**Parameters]:
    def __get__[Row](
        self, instance: object, owner: type[Row]
    ) -> BoundInsert[Parameters, Row]: ...

def insert_using[**Parameters, Input](
    factory: Callable[Parameters, Input],
) -> InsertUsing[Parameters]: ...
def required[Value]() -> Field[Value]: ...

@dataclass_transform(
    field_specifiers=(field, required), kw_only_default=True, frozen_default=True
)
class RefinedModel: ...

def update[Owner](model: type[Owner], first: Assignment[Owner]) -> Write[int]: ...

class GeneratedValue[Value, Missing]:
    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> Column[Owner, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value | Missing: ...
    def __set__(self, instance: object, value: Value | Missing) -> None: ...

def server[Value, Missing](*, default: Omitted) -> GeneratedValue[Value, Missing]: ...

@dataclass_transform(
    field_specifiers=(field, server), kw_only_default=True, frozen_default=True
)
class ValueModel: ...

class Table[**Parameters, Input, Row]:
    def __init__(
        self, input_type: Callable[Parameters, Input], row_type: type[Row]
    ) -> None: ...
    def new(self, *args: Parameters.args, **kwargs: Parameters.kwargs) -> Input: ...
    def insert(self, value: Input) -> Write[Row]: ...
    def create(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Write[Row]: ...
    def select(self) -> Query[Row]: ...

class Factory[**Parameters, Row]:
    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Write[Row]: ...

def command_model[**Parameters, Row](
    model: Callable[Parameters, Row],
) -> Factory[Parameters, Row]: ...

_Target = TypeVar("_Target")

class ForeignColumn(Column[_Owner, _Value], Generic[_Owner, _Target, _Value]):
    def references(
        self, target: Column[_Target, _Value]
    ) -> Predicate[tuple[_Owner, _Target]]: ...

class Foreign(Field[_Value], Generic[_Target, _Value]):
    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> ForeignColumn[Owner, _Target, _Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> _Value: ...

def foreign[Target, Value](target: Column[Target, Value]) -> Foreign[Target, Value]: ...

class ErasedForeign(Field[_Value], Generic[_Target, _Value]): ...

def erased_foreign[Target, Value](
    target: Column[Target, Value],
) -> ErasedForeign[Target, Value]: ...

@dataclass_transform(field_specifiers=(field, erased_foreign), kw_only_default=True)
class ErasedRelations(Model): ...

@dataclass_transform(field_specifiers=(field, foreign), kw_only_default=True)
class RelatedModel(Model): ...

def property_field[Owner, Value](
    function: Callable[[Owner], Value],
) -> Field[Value]: ...
