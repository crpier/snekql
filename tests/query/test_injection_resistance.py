"""End-to-end SQL-injection resistance tests for the SQLite runtime.

The compile-level properties in ``tests/test_query_compilation_properties.py``
prove that every bound value becomes a placeholder, and
``tests/test_identifier_validation_properties.py`` proves a hostile *identifier*
is rejected at declaration. What neither does is execute a classic breakout
payload against a live database and then inspect, with the raw ``sqlite3``
driver, that the attack had no effect: the schema still stands and the payload
was stored as ordinary data.

These tests close that loop. Each drives a real end-to-end path -- insert /
where / like / in / between / update-set -- with the canonical injection
strings as *values*, then reopens the file with the stdlib driver to assert the
table survived and every payload round-tripped verbatim. A regression that
spliced a value into SQL text instead of binding it would return extra rows or
corrupt the stored data -- caught here by the exact row-count and verbatim
round-trip assertions, which are the primary proof.

One caveat about scope: the runtime executes a single statement per ``execute``
call (``sqlite3``'s ``Cursor.execute`` raises on stacked statements), so a
smuggled ``; DROP TABLE`` could not itself drop the table even if a regression
spliced it into the text. The schema-survival checks are therefore a
belt-and-suspenders guard against that single-statement assumption regressing --
not the assertion that carries the injection-safety proof.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, assert_true, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    insert,
    select,
    update,
)
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import initialized_database

# The canonical breakout shapes: closing a string/identifier quote and
# appending a second statement, tautologies, comment terminators, UNION
# smuggling, a stacked DELETE, and an embedded NUL. The default table name for
# ``Account`` is ``account`` (lowercased class name), so the DROP targets that.
_INJECTION_VALUES = (
    "'; DROP TABLE account; --",
    'x"; DROP TABLE account; --',
    "1' OR '1'='1",
    "' OR 1=1 --",
    "admin'--",
    "'; DELETE FROM account; --",
    "') OR ('1'='1",
    "100%' UNION SELECT secret FROM account --",
    "a\x00b",
    "\\'; DROP TABLE account; --",
    "'||(SELECT status FROM account)||'",
)


class Account[S = Pending](Model[S, "Account[Fetched]"]):
    """Model whose text columns receive the injection payloads as data."""

    id: Account.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    email: Account.Col[str] = Text(nullable=False)
    status: Account.Col[str] = Text(nullable=False, default="active")


def _surviving_tables(database_path: Path) -> set[str]:
    """Table names in the file, read with the stdlib driver (no snekql)."""

    connection = connect(database_path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()


@test(mark="medium")
async def injection_payloads_insert_as_literal_data() -> None:
    """Breakout strings inserted as values are stored verbatim; the table and
    every row survive, so no payload ran as SQL."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await initialized_database(database=database_path, models=[Account])
        try:
            async with database.transaction() as tx:
                for payload in _INJECTION_VALUES:
                    _ = await tx.execute(insert(Account(email=payload)))
                rows = await tx.fetch_all(select(Account).all())
        finally:
            await database.close()

        # Every payload became exactly one row -- none opened a second statement.
        assert_eq(len(rows), len(_INJECTION_VALUES))
        assert_eq({row.email for row in rows}, set(_INJECTION_VALUES))

        # The raw driver confirms the schema is intact and the data is literal.
        assert_true("account" in _surviving_tables(database_path))
        connection = connect(database_path)
        try:
            stored = {row[0] for row in connection.execute("SELECT email FROM account")}
        finally:
            connection.close()
        assert_eq(stored, set(_INJECTION_VALUES))


@test(mark="medium")
async def eq_predicate_treats_payload_as_a_value_not_sql() -> None:
    """``eq`` with a tautology payload matches only the row whose value is that
    literal string -- it does not return every row the way a spliced
    ``OR '1'='1'`` would."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await initialized_database(database=database_path, models=[Account])
        try:
            async with database.transaction() as tx:
                _ = await tx.execute(insert(Account(email="alice@example.com")))
                _ = await tx.execute(insert(Account(email="bob@example.com")))
                for payload in _INJECTION_VALUES:
                    _ = await tx.execute(insert(Account(email=payload)))

            async with database.transaction() as tx:
                for payload in _INJECTION_VALUES:
                    # The compiled SQL must carry the payload only as a bound
                    # parameter -- never spliced into the statement text.
                    sql, params = compile_sqlite_select_sql(
                        select(Account).where(Account.email.eq(payload))
                    )
                    assert_eq(sql.count("?"), 1)
                    assert_eq(params, (payload,))
                    assert_true("DROP" not in sql.upper())

                    matched = await tx.fetch_all(
                        select(Account).where(Account.email.eq(payload))
                    )
                    assert_eq(len(matched), 1)
                    assert_eq(matched[0].email, payload)

                # The tautology string was itself inserted as one row, so eq
                # matches exactly that single literal -- not every row, the way a
                # spliced ``OR '1'='1'`` would.
                tautology_match = await tx.fetch_all(
                    select(Account).where(Account.email.eq("1' OR '1'='1"))
                )
                assert_eq(
                    len(tautology_match), 1
                )  # the one stored literal, not all rows
        finally:
            await database.close()


@test(mark="medium")
async def like_in_and_between_bind_payloads_as_parameters() -> None:
    """The pattern/list/range predicates bind their operands, so wildcard- and
    quote-laden payloads never reach the SQL text."""

    like_payload = "100%' UNION SELECT status FROM account --"
    in_payloads = ("'; DROP TABLE account; --", "x' OR '1'='1")
    between_low = "'; DELETE FROM account; --"
    between_high = "zzz'; DROP TABLE account; --"

    like_sql, like_params = compile_sqlite_select_sql(
        select(Account).where(Account.email.like(like_payload))
    )
    assert_eq(like_sql.count("?"), 1)
    assert_eq(like_params, (like_payload,))
    assert_true("UNION" not in like_sql.upper())

    in_sql, in_params = compile_sqlite_select_sql(
        select(Account).where(Account.email.in_(*in_payloads))
    )
    assert_eq(in_sql.count("?"), len(in_payloads))
    assert_eq(in_params, in_payloads)
    assert_true("DROP" not in in_sql.upper())

    between_sql, between_params = compile_sqlite_select_sql(
        select(Account).where(Account.email.between(between_low, between_high))
    )
    assert_eq(between_sql.count("?"), 2)
    assert_eq(between_params, (between_low, between_high))
    assert_true("DELETE" not in between_sql.upper())


@test(mark="medium")
async def update_set_stores_payload_without_touching_schema() -> None:
    """A payload assigned through ``update().set()`` is stored as data; the
    table and its rows are untouched by any smuggled statement."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await initialized_database(database=database_path, models=[Account])
        payload = "'; DROP TABLE account; --"
        try:
            async with database.transaction() as tx:
                _ = await tx.execute(insert(Account(email="carol@example.com")))
                _ = await tx.execute(insert(Account(email="dave@example.com")))

            async with database.transaction() as tx:
                _ = await tx.execute(
                    update(Account)
                    .set(Account.status.to(payload))
                    .where(Account.email.eq("carol@example.com"))
                )

            async with database.transaction() as tx:
                rows = await tx.fetch_all(select(Account).all())
        finally:
            await database.close()

        # Both rows survive; only carol's status changed, to the literal payload.
        assert_eq(len(rows), 2)
        by_email = {row.email: row.status for row in rows}
        assert_eq(by_email["carol@example.com"], payload)
        assert_eq(by_email["dave@example.com"], "active")
        assert_true("account" in _surviving_tables(database_path))


@test(mark="fast")
async def limit_and_offset_reject_non_integer_operands() -> None:
    """``LIMIT``/``OFFSET`` take bound integers; a string operand (a common
    injection point in string-built SQL) is refused at construction, so it can
    never reach the statement text."""

    for bad in ("1; DROP TABLE account", "1 OR 1=1", "-1"):
        with assert_raises(QueryConstructionError):
            _ = select(Account).all().limit(bad)  # pyright: ignore[reportArgumentType]
        with assert_raises(QueryConstructionError):
            _ = select(Account).all().offset(bad)  # pyright: ignore[reportArgumentType]

    # A legitimate integer limit binds as a placeholder, not inlined text.
    sql, params = compile_sqlite_select_sql(select(Account).all().limit(5).offset(10))
    assert_eq(sql.count("?"), 2)
    assert_eq(params, (5, 10))
