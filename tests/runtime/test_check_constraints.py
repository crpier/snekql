"""Named CHECK declarations through public schema interfaces."""

from gc import collect
from typing import Any, ClassVar
from warnings import catch_warnings

from pydantic import Json
from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@test(mark="fast")
def check_scaffold_preserves_boolean_structure() -> None:
    """Deferred declarations compare bound local columns without parameters."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()
        ceiling: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [
                sqlite.CheckConstraint(
                    cls.balance.gte(0) & cls.balance.lte_col(cls.ceiling),
                    name="ck_account_balance",
                )
            ]

    assert_in(
        'CONSTRAINT "ck_account_balance" CHECK (("balance" >= 0) AND ("balance" <= "ceiling"))',
        sqlite.scaffold([Account]),
    )


@test(
    [
        Param(value=operation, name=operation)
        for operation in ("null", "not-null", "in", "not-in", "between", "not", "or")
    ],
    mark="fast",
)
def bounded_predicates_have_explicit_sql(operation: str) -> None:
    """Only the selected predicate family is emitted for each declaration."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int | None] = sqlite.Integer(nullable=True)

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            predicate = {
                "null": cls.balance.is_null(),
                "not-null": cls.balance.is_not_null(),
                "in": cls.balance.in_(1, 2),
                "not-in": cls.balance.not_in(1, 2),
                "between": cls.balance.between(1, 2),
                "not": ~cls.balance.gte(0),
                "or": cls.balance.is_null() | cls.balance.gte(0),
            }[operation]
            return [sqlite.CheckConstraint(predicate, name="ck_balance")]

    expected = {
        "null": '"balance" IS NULL',
        "not-null": '"balance" IS NOT NULL',
        "in": '"balance" IN (1, 2)',
        "not-in": '"balance" NOT IN (1, 2)',
        "between": '"balance" BETWEEN 1 AND 2',
        "not": 'NOT ("balance" >= 0)',
        "or": '("balance" IS NULL) OR ("balance" >= 0)',
    }[operation]
    assert_in(f'CONSTRAINT "ck_balance" CHECK ({expected})', sqlite.scaffold([Account]))


@test(mark="medium")
async def sqlite_check_rejects_invalid_pair() -> None:
    """Exercise the declared CHECK through native database enforcement."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()
        ceiling: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [
                sqlite.CheckConstraint(
                    cls.balance.gte(0) & cls.balance.lte_col(cls.ceiling),
                    name="ck_balance",
                )
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Account])})
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.insert(Account(balance=5, ceiling=4)))


@test(mark="medium")
async def sqlite_null_satisfies_check() -> None:
    """Exercise the declared CHECK through native database enforcement."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int | None] = sqlite.Integer(nullable=True)

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="ck_balance")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Account(balance=None)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Account.balance))

    assert_eq(rows, [None])


@test(mark="medium")
async def sqlite_text_literal_is_not_sql() -> None:
    """Exercise the declared CHECK through native database enforcement."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [
                sqlite.CheckConstraint(
                    cls.balance.eq("quote'\\nul\0; DROP TABLE account; --é"),
                    name="ck_balance",
                )
            ]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(Account(balance="quote'\\nul\0; DROP TABLE account; --é"))
            )
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Account.balance))

    assert_eq(rows, ["quote'\\nul\0; DROP TABLE account; --é"])


@test(mark="medium")
async def sqlite_boolean_literal_uses_storage_codec() -> None:
    """Exercise the declared CHECK through native database enforcement."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[bool] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.eq(True), name="ck_balance")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Account(balance=True)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.select(Account.balance))

    assert_eq(rows, [True])


@test(mark="slow")
async def mariadb_check_rejects_invalid_pair() -> None:
    """Exercise the declared CHECK through native database enforcement."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[int] = mariadb.Integer()
        ceiling: mariadb.Col[int] = mariadb.Integer()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            return [
                mariadb.CheckConstraint(
                    cls.balance.gte(0) & cls.balance.lte_col(cls.ceiling),
                    name="ck_balance",
                )
            ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Account])})
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.insert(Account(balance=5, ceiling=4)))


@test(mark="slow")
async def mariadb_null_satisfies_check() -> None:
    """Exercise the declared CHECK through native database enforcement."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[int | None] = mariadb.Integer(nullable=True)

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            return [mariadb.CheckConstraint(cls.balance.gte(0), name="ck_balance")]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account(balance=None)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Account.balance))

    assert_eq(rows, [None])


@test(mark="slow")
async def mariadb_text_literal_is_not_sql() -> None:
    """Exercise the declared CHECK through native database enforcement."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[str] = mariadb.Text()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            return [
                mariadb.CheckConstraint(
                    cls.balance.eq("quote'\\nul\0; DROP TABLE account; --é"),
                    name="ck_balance",
                )
            ]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(
                    Account(balance="quote'\\nul\0; DROP TABLE account; --é")
                )
            )
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Account.balance))

    assert_eq(rows, ["quote'\\nul\0; DROP TABLE account; --é"])


@test(mark="slow")
async def mariadb_boolean_literal_uses_storage_codec() -> None:
    """Exercise the declared CHECK through native database enforcement."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[bool] = mariadb.Boolean()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            return [mariadb.CheckConstraint(cls.balance.eq(True), name="ck_balance")]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Account])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account(balance=True)))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(Account.balance))

    assert_eq(rows, [True])


@test(
    [
        Param(value=case, name=case)
        for case in ("match", "missing", "changed", "unsupported")
    ],
    mark="medium",
)
async def sqlite_verifies_hand_created_check(case: str) -> None:
    """Verification distinguishes presence, supported structure, and unknown SQL."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="ck_balance")]

    clauses = {
        "match": ', CONSTRAINT "ck_balance" CHECK ((balance >= (0)))',
        "missing": "",
        "changed": ", CONSTRAINT ck_balance CHECK (balance > 0)",
        "unsupported": ", CONSTRAINT ck_balance CHECK (abs(balance) >= 0)",
    }
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE account (balance INTEGER NOT NULL{clauses[case]}) STRICT"
            }
        )
        report = await database.verify([Account], policy="warn")

    expected = {
        "match": [("check.presence", "matched"), ("check.expression", "matched")],
        "missing": [("check.presence", "drift")],
        "changed": [("check.presence", "matched"), ("check.expression", "drift")],
        "unsupported": [
            ("check.presence", "matched"),
            ("check.expression", "unchecked"),
        ],
    }[case]
    assert_eq(
        [
            (fact.kind, fact.status)
            for fact in report.facts
            if fact.object_name == "ck_balance"
        ],
        expected,
    )


@test(
    [
        Param(value=case, name=case)
        for case in ("match", "missing", "changed", "unsupported")
    ],
    mark="slow",
)
async def mariadb_verifies_hand_created_check(case: str) -> None:
    """Verification distinguishes presence, supported structure, and unknown SQL."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[int] = mariadb.Integer()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            return [mariadb.CheckConstraint(cls.balance.gte(0), name="ck_balance")]

    clauses = {
        "match": ", CONSTRAINT `ck_balance` CHECK ((balance >= (0)))",
        "missing": "",
        "changed": ", CONSTRAINT ck_balance CHECK (balance > 0)",
        "unsupported": ", CONSTRAINT ck_balance CHECK (abs(balance) >= 0)",
    }
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE account (balance BIGINT NOT NULL{clauses[case]}) ENGINE=InnoDB"
            }
        )
        report = await database.verify([Account], policy="warn")

    expected = {
        "match": [("check.presence", "matched"), ("check.expression", "matched")],
        "missing": [("check.presence", "drift")],
        "changed": [("check.presence", "matched"), ("check.expression", "drift")],
        "unsupported": [
            ("check.presence", "matched"),
            ("check.expression", "unchecked"),
        ],
    }[case]
    assert_eq(
        [
            (fact.kind, fact.status)
            for fact in report.facts
            if fact.object_name == "ck_balance"
        ],
        expected,
    )


@test(
    [
        Param(value=case, name=case)
        for case in (
            "comparison",
            "null",
            "not-null",
            "in",
            "not-in",
            "between",
            "not-between",
            "not-compound",
            "not-in-negated",
            "not",
            "or",
            "boolean",
            "text",
            "empty-text",
        )
    ],
    mark="medium",
)
async def sqlite_scaffold_checks_verify(case: str) -> None:
    """Every supported declaration survives native catalog normalization."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int | None] = sqlite.Integer(nullable=True)
        flag: sqlite.Col[bool] = sqlite.Integer()
        label: sqlite.Col[str] = sqlite.Text()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            predicates = {
                "comparison": cls.balance.gte(-5),
                "null": cls.balance.is_null(),
                "not-null": cls.balance.is_not_null(),
                "in": cls.balance.in_(1, 2),
                "not-in": cls.balance.not_in(1, 2),
                "between": cls.balance.between(1, 2),
                "not-between": ~cls.balance.between(1, 2),
                "not-compound": ~(cls.balance.gte(0) & cls.flag.eq(True)),
                "not-in-negated": ~cls.balance.in_(1, 2),
                "not": ~cls.balance.gte(0),
                "or": cls.balance.is_null() | cls.balance.gte(0),
                "boolean": cls.flag.eq(True),
                "text": cls.label.eq("quote'\\nul\0é"),
                "empty-text": cls.label.eq(""),
            }
            return [sqlite.CheckConstraint(predicates[case], name="ck_rule")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Account])})
        report = await database.verify([Account])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.expression"],
        ["matched"],
    )


@test(
    [
        Param(value=case, name=case)
        for case in (
            "comparison",
            "null",
            "not-null",
            "in",
            "not-in",
            "between",
            "not-between",
            "not-compound",
            "not-in-negated",
            "not",
            "or",
            "boolean",
            "text",
            "empty-text",
        )
    ],
    mark="slow",
)
async def mariadb_scaffold_checks_verify(case: str) -> None:
    """Every supported declaration survives native catalog normalization."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        balance: mariadb.Col[int | None] = mariadb.Integer(nullable=True)
        flag: mariadb.Col[bool] = mariadb.Boolean()
        label: mariadb.Col[str] = mariadb.Text()

        @classmethod
        def __checks__(cls) -> list[mariadb.CheckConstraint[Account[S]]]:
            predicates = {
                "comparison": cls.balance.gte(-5),
                "null": cls.balance.is_null(),
                "not-null": cls.balance.is_not_null(),
                "in": cls.balance.in_(1, 2),
                "not-in": cls.balance.not_in(1, 2),
                "between": cls.balance.between(1, 2),
                "not-between": ~cls.balance.between(1, 2),
                "not-compound": ~(cls.balance.gte(0) & cls.flag.eq(True)),
                "not-in-negated": ~cls.balance.in_(1, 2),
                "not": ~cls.balance.gte(0),
                "or": cls.balance.is_null() | cls.balance.gte(0),
                "boolean": cls.flag.eq(True),
                "text": cls.label.eq("quote'\\nul\0é"),
                "empty-text": cls.label.eq(""),
            }
            return [mariadb.CheckConstraint(predicates[case], name="ck_rule")]

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Account])})
        report = await database.verify([Account])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.expression"],
        ["matched"],
    )


@test(
    [
        Param(value=case, name=case)
        for case in (
            "foreign-left",
            "foreign-right",
            "bad-name",
            "duplicate-name",
            "bad-return",
            "bad-entry",
            "raw-sql",
            "real",
            "wrong-literal",
            "too-large",
            "like",
            "subquery",
            "mismatched-columns",
        )
    ],
    mark="fast",
)
def invalid_checks_fail_before_io(case: str) -> None:
    """Only bounded predicates over the declaring table reach schema compilation."""

    class Other[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Other[sqlite.Row]]]
        value: sqlite.Col[int] = sqlite.Integer()

    with assert_raises(sqlite.ModelDeclarationError):

        class Account[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
            balance: sqlite.Col[int] = sqlite.Integer()
            label: sqlite.Col[str] = sqlite.Text()
            amount: sqlite.Col[float] = sqlite.Real()

            @classmethod
            def __checks__(cls) -> Any:
                if case == "bad-return":
                    return ()
                if case == "bad-entry":
                    return [cls.balance.gte(0)]
                if case == "raw-sql":
                    return [sqlite.CheckConstraint("balance >= 0", name="ck_balance")]  # ty: ignore[invalid-argument-type]
                if case == "wrong-literal":
                    return [sqlite.CheckConstraint(cls.label.eq(0), name="ck_balance")]  # ty: ignore[invalid-argument-type]
                predicates = {
                    "foreign-left": Other.value.gte(0),
                    "foreign-right": cls.balance.gte_col(Other.value),
                    "bad-name": cls.balance.gte(0),
                    "duplicate-name": cls.balance.gte(0),
                    "real": cls.amount.gte(0),
                    "too-large": cls.balance.gte(2**80),
                    "like": cls.label.like("a%"),
                    "subquery": cls.balance.in_subquery(sqlite.select(Other.value)),
                    "mismatched-columns": cls.balance.eq_col(cls.label),  # ty: ignore[no-matching-overload]
                }
                checks = [
                    sqlite.CheckConstraint(
                        predicates[case],
                        name="bad name" if case == "bad-name" else "ck_balance",
                    )
                ]
                return checks * 2 if case == "duplicate-name" else checks


@test(mark="fast")
def checks_are_bound_once() -> None:
    """Scaffolding reuses the immutable declaration rather than rerunning user code."""
    calls: list[str] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            calls.append("bound")
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="ck_balance")]

    sqlite.scaffold([Account])
    sqlite.scaffold([Account])

    assert_eq(calls, ["bound"])


@test(mark="medium")
async def sqlite_null_keyword_is_not_a_quoted_column() -> None:
    """A keyword cannot be certified as the identically spelled local column."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        NULL: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.NULL.gte(0), name="ck_rule")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": 'CREATE TABLE account ("NULL" INTEGER NOT NULL, CONSTRAINT ck_rule CHECK (NULL >= 0)) STRICT'
            }
        )
        report = await database.verify([Account])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.expression"],
        ["unchecked"],
    )


@test(mark="fast")
def asynchronous_check_factory_is_not_started() -> None:
    """Reject async declarations without leaking an unawaited coroutine."""
    with catch_warnings(record=True) as captured:
        with assert_raises(sqlite.ModelDeclarationError):

            class Account[S = sqlite.Pending](sqlite.Model[S]):
                __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
                balance: sqlite.Col[int] = sqlite.Integer()

                @classmethod
                async def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
                    return [
                        sqlite.CheckConstraint(cls.balance.gte(0), name="ck_balance")
                    ]

        collect()

    assert_eq([warning.category for warning in captured], [])


@test(
    [
        Param(value=expression, name=name)
        for name, expression in (
            ("arithmetic", "balance + 0 >= 0"),
            ("function", "abs(balance) >= 0"),
            ("unary-column", "+balance >= 0"),
            ("cast", "cast(balance as integer) >= 0"),
        )
    ],
    mark="medium",
)
async def unsupported_sqlite_expression_is_not_a_match(expression: str) -> None:
    """Unknown syntax stays unchecked even when a human could prove equivalence."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="ck_rule")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": f"CREATE TABLE account (balance INTEGER NOT NULL, CONSTRAINT ck_rule CHECK ({expression})) STRICT"
            }
        )
        report = await database.verify([Account])

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.expression"],
        ["unchecked"],
    )


@test(mark="fast")
def check_rejects_json_text_storage() -> None:
    """JSON-encoded logical strings are not ordinary SQL text operands."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Account[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
            label: sqlite.Col[Json[str]] = sqlite.Text()

            @classmethod
            def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
                return [
                    sqlite.CheckConstraint(cls.label.is_not_null(), name="ck_label")
                ]


@test(mark="medium")
async def unmanaged_checks_share_one_fact_per_name() -> None:
    """Anonymous catalog checks must not create duplicate fact identities."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE account (balance INTEGER NOT NULL, CHECK (balance >= 0), CHECK (balance <= 10)) STRICT"
            }
        )
        report = await database.verify([Account])

    assert_eq(
        [
            (fact.object_name, fact.status)
            for fact in report.facts
            if fact.kind == "check.unmanaged"
        ],
        [(None, "unchecked")],
    )


@test(mark="fast")
def check_rejects_invalid_unicode_literal() -> None:
    """Unencodable text is a declaration error rather than a later driver failure."""
    with assert_raises(sqlite.ModelDeclarationError):

        class Account[S = sqlite.Pending](sqlite.Model[S]):
            __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
            label: sqlite.Col[str] = sqlite.Text()

            @classmethod
            def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
                return [sqlite.CheckConstraint(cls.label.eq("\ud800"), name="ck_label")]


@test(mark="medium")
async def non_sql_whitespace_is_not_discarded() -> None:
    """A nonbreaking-space identifier is not the numeric literal that follows it."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        balance: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="ck_rule")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": 'CREATE TABLE account (balance INTEGER NOT NULL, "\u00a00" INTEGER NOT NULL, CONSTRAINT ck_rule CHECK(balance >= \u00a00)) STRICT'
            }
        )
        report = await database.verify([Account], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.expression"],
        ["unchecked"],
    )


@test(mark="medium")
async def unicode_identifier_is_not_constraint_keyword() -> None:
    """Unicode uppercasing must not invent a CONSTRAINT name from a column."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        constraınt: sqlite.Col[int] = sqlite.Integer()  # noqa: PLC2401 - intentional SQL keyword lookalike
        balance: sqlite.Col[int] = sqlite.Integer()

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
            return [sqlite.CheckConstraint(cls.balance.gte(0), name="INTEGER")]

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        await database.migrate(
            {
                "001": "CREATE TABLE account (constra\u0131nt INTEGER CHECK(balance >= 0) NOT NULL, balance INTEGER NOT NULL) STRICT"
            }
        )
        report = await database.verify([Account], policy="warn")

    assert_eq(
        [fact.status for fact in report.facts if fact.kind == "check.presence"],
        ["drift"],
    )
