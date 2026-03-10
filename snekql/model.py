import dataclasses
from typing import Any, Type, dataclass_transform

from pydantic.dataclasses import dataclass


@dataclasses.dataclass(frozen=True)
class ClassAttr:
    """
    Represents a class attribute with its name, annotation, and default value.
    """

    name: str
    annotation: Any
    default: Any

    def __repr__(self) -> str:
        return f"{self.name}"


@dataclass_transform(kw_only_default=True)
class ModelMetaclass(type):
    def __new__(
        cls, name: str, bases: tuple[Type, ...], namespace: dict[str, Any]
    ) -> Type:
        new_cls = super().__new__(cls, name, bases, namespace)
        new_cls = dataclass(new_cls, kw_only=True)

        for attr_name, field_obj in new_cls.__dataclass_fields__.items():
            default_value: Any = None
            if field_obj.default is not dataclasses.MISSING:
                default_value = field_obj.default
            elif field_obj.default_factory is not dataclasses.MISSING:
                default_value = field_obj.default_factory

            setattr(
                new_cls,
                attr_name,
                ClassAttr(
                    name=attr_name, annotation=field_obj.type, default=default_value
                ),
            )

        return new_cls  # pyright: ignore[reportReturnType]


class Base(metaclass=ModelMetaclass):
    rowid: int | None = None


class User(Base):
    name: str
    age: int
    email: str
