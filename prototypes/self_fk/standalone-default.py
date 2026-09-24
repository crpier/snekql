"""Owner-binding reduction, independent of snekql and its dependencies."""
from typing import dataclass_transform, overload, reveal_type

class Unbound: ...

class Column[Owner, Value]:
    @overload
    def __get__[Bound](self, instance: None, owner: type[Bound]) -> Column[Bound, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__(self, instance: object, owner: type[object]) -> object:
        return self
    def __set__(self, instance: object, value: Value) -> None:
        pass
    def owner(self, owner: Owner) -> Owner:
        return owner

class Reference[Target, Value](Column[Unbound, Value]):
    def target(self, target: Target) -> Target:
        return target

@overload
def column[Value](*, default: Value) -> Column[Unbound, Value]: ...
@overload
def column[Value]() -> Column[Unbound, Value]: ...
def column(*, default: object = None) -> object:
    return Column()

@overload
def reference[Target, Value](target: Column[Target, Value]) -> Reference[Target, Value]: ...
@overload
def reference[Target, Value](target: Column[Target, Value], *, default: None) -> Reference[Target, Value | None]: ...

def reference(target: object, *, default: object = None) -> object:
    return Reference()

@dataclass_transform(field_specifiers=(column, reference), kw_only_default=True)
class Meta(type): ...
class Model(metaclass=Meta): ...

class Transformed(Model):
    key: Column[Unbound, int] = column(default=1)
    reveal_type(key)
    retained: Reference[Unbound, int | None] = reference(key, default=None)
    parent: Reference[Transformed, int | None] = reference(key, default=None)

class Plain:
    key: Column[Unbound, int] = column(default=1)
    reveal_type(key)
    retained: Reference[Unbound, int | None] = reference(key, default=None)
    parent: Reference[Plain, int | None] = reference(key, default=None)

class External(Model):
    parent: Reference[Transformed, int | None] = reference(Transformed.key, default=None)

reveal_type(Transformed.key)
