"""New class-body MariaDB witness and paired native-codec execution."""

from typing import ClassVar

from snekql import mariadb
from snektest import assert_in, test


@test(mark="fast")
def maria_witness_preserves_native_storage() -> None:
    from scratchpad.paired_situations.body_maria import Model, ReadType

    class Product[State = mariadb.Pending](Model[State]):
        __read_type__: ClassVar[ReadType[Product[mariadb.Fetched]]]
        price: mariadb.Col[int] = mariadb.Integer()

    assert_in("`price` BIGINT NOT NULL", mariadb.scaffold([Product]))


@test(mark="fast")
def product_scaffold_matches_between_approaches() -> None:
    from snektest import assert_eq

    from scratchpad.paired_situations import body, nested

    assert_eq(nested.mariadb.scaffold(nested.Product), mariadb.scaffold([body.Product]))
