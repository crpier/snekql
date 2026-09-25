"""Tightening constructor typing must keep the declared storage behavior."""

from typing import ClassVar, Literal

from snektest import assert_eq, test


@test(mark="fast")
def typed_default_keeps_the_input_default() -> None:
    from scratchpad.dual_typing_parity import strict_columns as sqlite

    class Input(sqlite.Model):
        __row__: ClassVar[type[Row]]
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        status: sqlite.Col[Literal["queued", "done"]] = sqlite.Text(default="queued")

    class Row(Input, sqlite.Row):
        table_name = "status_defaults"

    assert_eq(Input(key=1).status, "queued")
