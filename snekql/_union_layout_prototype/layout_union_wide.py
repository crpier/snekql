"""Twelve fields retain independent optionality without union overloads."""

from typing import assert_type

from layout_union import integer, optional_integer, project, value
from wide_fields import WideFields

left = project(
    WideFields(
        field_0=optional_integer(),
        field_1=integer(),
        field_2=integer(),
        field_3=optional_integer(),
        field_4=integer(),
        field_5=integer(),
        field_6=optional_integer(),
        field_7=integer(),
        field_8=integer(),
        field_9=optional_integer(),
        field_10=integer(),
        field_11=integer(),
    )
)
right = project(
    WideFields(
        field_11=integer(),
        field_10=optional_integer(),
        field_9=integer(),
        field_8=integer(),
        field_7=optional_integer(),
        field_6=integer(),
        field_5=integer(),
        field_4=optional_integer(),
        field_3=integer(),
        field_2=integer(),
        field_1=optional_integer(),
        field_0=integer(),
    )
)
combined = left.union_all(right)
assert_type(value(combined.columns.field_0), int | None)
assert_type(value(combined.columns.field_1), int | None)
assert_type(value(combined.columns.field_2), int)
assert_type(value(combined.columns.field_3), int | None)
assert_type(value(combined.columns.field_4), int | None)
assert_type(value(combined.columns.field_5), int)
assert_type(value(combined.columns.field_6), int | None)
assert_type(value(combined.columns.field_7), int | None)
assert_type(value(combined.columns.field_8), int)
assert_type(value(combined.columns.field_9), int | None)
assert_type(value(combined.columns.field_10), int | None)
assert_type(value(combined.columns.field_11), int)
