"""Deferred scalar relationships through model and schema interfaces."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from typing import Any, ClassVar, Self

from anyio import to_thread
from snektest import Param, assert_eq, assert_in, assert_is, assert_raises, test

from snekql import sqlite


@test(mark="fast")
async def self_target_resolves_after_declaration() -> None:
    """A callable can name its enclosing model once Python has bound the name."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=sqlite.PENDING_GENERATION,
        )
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id,
            default=None,
        )

    ddl = sqlite.scaffold([Account])

    assert_in("FOREIGN KEY", ddl)


@test(mark="fast")
async def callback_runs_once_across_model_uses() -> None:
    """Construction and repeated scaffolding share the resolved target."""
    calls: list[str] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=sqlite.PENDING_GENERATION,
        )
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: (calls.append("target"), Account.account_id)[1],
            default=None,
        )

    assert_eq(calls, [])
    account = Account()
    sqlite.scaffold([Account])
    sqlite.scaffold([Account])

    assert_eq(account.manager_id, None)
    assert_eq(calls, ["target"])


@test(mark="fast")
async def deferred_column_can_have_a_class_body_index() -> None:
    """Index declarations wait for actual target storage rather than a placeholder."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=sqlite.PENDING_GENERATION,
        )
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id,
            default=None,
        )
        __indexes__: ClassVar = [sqlite.Index(manager_id)]

    ddl = sqlite.scaffold([Account])

    assert_in("CREATE INDEX", ddl)


@test(mark="fast")
async def cyclic_target_storage_fails_closed() -> None:
    """Mutually dependent derived storage cannot manufacture a concrete key type."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=sqlite.PENDING_GENERATION,
        )
        first: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.second,
            default=None,
            unique=True,
        )
        second: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.first,
            default=None,
            unique=True,
        )

    with assert_raises(sqlite.ModelDeclarationError) as failure:
        sqlite.scaffold([Account])

    assert_in("cyclic declaration binding", str(failure.exception))


@test(mark="fast")
async def explicit_constraint_can_target_a_deferred_column() -> None:
    """A table-level constraint validates the resolved key rather than forcing lookup early."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=sqlite.PENDING_GENERATION,
        )
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id,
            default=None,
            unique=True,
        )
        alias_id: sqlite.Col[int | None] = sqlite.Integer(default=None)
        __foreign_keys__: ClassVar = [
            sqlite.ForeignKeyConstraint(alias_id, references=(manager_id,))
        ]

    ddl = sqlite.scaffold([Account])

    assert_in('("alias_id") REFERENCES "account" ("manager_id")', ddl)


@test(mark="fast")
async def resolver_failure_is_terminal() -> None:
    """Repeated model uses cannot retry application code after a failed binding."""
    calls: list[str] = []

    def fail() -> Any:
        calls.append("target")
        msg = "target failed"
        raise sqlite.ModelDeclarationError(msg)

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            fail, default=None
        )

    for _ in range(3):
        with assert_raises(sqlite.ModelDeclarationError):
            sqlite.scaffold([Account])
    with assert_raises(sqlite.ModelDeclarationError):
        Account(account_id=1)

    assert_eq(calls, ["target"])


@test(mark="fast")
async def resolved_target_cannot_follow_later_rebinding() -> None:
    """A cached physical target cannot change when its callback closure changes."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        alternate: sqlite.Col[int] = sqlite.Integer(unique=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: chosen, default=None
        )

    chosen = Account.account_id
    before = sqlite.scaffold([Account])
    chosen = Account.alternate
    after = sqlite.scaffold([Account])

    assert_eq(after, before)
    assert_is(Account.manager_id.foreign_key_target, Account.account_id)


@test(mark="fast")
async def deferred_hooks_run_once_after_target_binding() -> None:
    """Index and check hooks see frozen concrete metadata, once on first use."""
    calls: list[str] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: (calls.append("target"), Account.account_id)[1],
            default=None,
        )

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            calls.append("index")
            assert_eq(cls.manager_id.storage_type_name, "Integer")
            with assert_raises(sqlite.FrozenModelError):
                cls.manager_id.unique = True
            return [sqlite.Index(cls.manager_id)]

        @classmethod
        def __checks__(cls) -> list[sqlite.CheckConstraint[Self]]:
            calls.append("check")
            return [
                sqlite.CheckConstraint(
                    cls.manager_id.is_null() | cls.manager_id.gt(0),
                    name="valid_manager",
                )
            ]

    assert_eq(calls, [])
    sqlite.scaffold([Account])
    sqlite.scaffold([Account])

    assert_eq(calls, ["target", "index", "check"])


@test(mark="fast")
async def invalid_hook_blocks_already_resolved_storage() -> None:
    """A failed model cannot expose a partial binding through column metadata."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id, default=None
        )

        @classmethod
        def __indexes__(cls) -> list[sqlite.Index[Self]]:
            msg = "invalid index declaration"
            raise sqlite.ModelDeclarationError(msg)

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.scaffold([Account])
    with assert_raises(sqlite.ModelDeclarationError):
        _ = Account.manager_id.storage_class


@test(mark="fast")
async def callback_cannot_redirect_to_another_model() -> None:
    """Untyped input still has to match the frozen annotated target identity."""

    class Other[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Other[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    # Simulate a callback from untyped application code.
    def wrong_target() -> Any:
        return Other.account_id

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            wrong_target, default=None
        )

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.scaffold([Account])


@test([Param(None, name="none"), Param(42, name="integer")], mark="fast")
async def callback_must_return_a_column(returned: object) -> None:
    """Invalid dynamic return values never masquerade as a typed-only FK."""

    def invalid() -> Any:
        return returned

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            invalid, default=None
        )

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.scaffold([Account])


@test(mark="fast")
async def storage_dependencies_can_resolve_without_a_cycle() -> None:
    """A self FK targeting another concrete-derived unique key is not a cycle."""

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        indirect: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.direct, default=None
        )
        direct: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id, default=None, unique=True
        )

    ddl = sqlite.scaffold([Account])

    assert_in('("indirect") REFERENCES "account" ("direct")', ddl)


@test(mark="fast")
async def callback_cannot_reenter_schema_construction() -> None:
    """Model-level reentry is rejected even when storage lookup itself is permitted."""

    def reenter() -> Any:
        sqlite.scaffold([Account])
        return Account.account_id

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            reenter, default=None
        )

    with assert_raises(sqlite.ModelDeclarationError) as failure:
        sqlite.scaffold([Account])

    assert_in("cyclic declaration binding", str(failure.exception))


@test(mark="fast")
async def concurrent_first_use_shares_one_resolution() -> None:
    """Independent callers wait for the same binding rather than running it twice."""
    calls: list[str] = []
    barrier = Barrier(4)

    def target() -> Any:
        calls.append("target")
        sleep(0.05)
        return Account.account_id

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            target, default=None
        )

    def scaffold() -> str:
        barrier.wait(timeout=5)
        return sqlite.scaffold([Account])

    def concurrent_scaffolds() -> list[str]:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(scaffold) for _ in range(4)]
            return [future.result(timeout=5) for future in futures]

    schemas = await to_thread.run_sync(concurrent_scaffolds)

    assert_eq(len(set(schemas)), 1)
    assert_eq(calls, ["target"])


@test(mark="fast")
async def class_body_index_list_is_snapshotted() -> None:
    """Changing an application list cannot rewrite an already captured declaration."""
    declarations: list[sqlite.Index[Any]] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id, default=None
        )
        __indexes__: ClassVar = declarations

    declarations.append(sqlite.Index(Account.manager_id, name="late_index"))
    ddl = sqlite.scaffold([Account])

    assert_eq("late_index" in ddl, False)


@test(mark="fast")
async def metadata_is_frozen_before_resolution() -> None:
    """Deferred storage is not a window for mutating declaration options."""
    calls: list[str] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: (calls.append("target"), Account.account_id)[1],
            default=None,
        )

    with assert_raises(sqlite.FrozenModelError):
        Account.manager_id.default = 9

    assert_eq(calls, [])


@test(mark="fast")
async def asynchronous_target_is_rejected_without_starting() -> None:
    """An async target cannot leak a coroutine from declaration setup."""
    calls: list[str] = []

    async def target() -> Any:
        calls.append("target")
        return None

    untyped_target: Any = target
    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.ForeignKey(untyped_target, default=None)

    assert_eq(calls, [])


@test(mark="fast")
async def default_is_required_even_for_dynamic_callbacks() -> None:
    """Runtime does not accept the omitted-default form excluded by static overloads."""

    def dynamic() -> Any:
        return None

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.ForeignKey(dynamic)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
async def interrupted_resolution_does_not_retry() -> None:
    """Process-control exceptions propagate while leaving the binding terminal."""
    calls: list[str] = []

    def interrupted() -> Any:
        calls.append("target")
        raise KeyboardInterrupt

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            interrupted, default=None
        )

    with assert_raises(KeyboardInterrupt):
        sqlite.scaffold([Account])
    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.scaffold([Account])

    assert_eq(calls, ["target"])


@test(
    [Param(value, name=value) for value in ("model", "key", "reference")], mark="fast"
)
async def query_use_resolves_pending_models(projection: str) -> None:
    """Even a projection of an ordinary column cannot bypass model binding."""
    calls: list[str] = []

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: (calls.append("target"), Account.account_id)[1],
            default=None,
        )

    if projection == "model":
        sqlite.select(Account).compile()
    elif projection == "key":
        sqlite.select(Account.account_id).compile()
    else:
        sqlite.select(Account.manager_id).compile()

    assert_eq(calls, ["target"])


@test(mark="fast")
async def failed_model_cannot_encode_an_ordinary_column() -> None:
    """An already-known storage type must not bypass the failed model contract."""

    def invalid() -> Any:
        return None

    class Account[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            invalid, default=None
        )

    with assert_raises(sqlite.ModelDeclarationError):
        sqlite.scaffold([Account])
    with assert_raises(sqlite.ModelDeclarationError):
        Account.account_id.encode(1, backend="sqlite")
