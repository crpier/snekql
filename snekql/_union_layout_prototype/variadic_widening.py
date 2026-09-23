"""A whole type pack does not itself compute a fieldwise union."""

from typing import assert_type

from variadic import Query, optional, required

assert_type(required().union_all(optional()), Query[int | None, str])
