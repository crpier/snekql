"""Public application behavior, compared with the body declaration variant."""

from collections.abc import AsyncGenerator

from snektest import assert_eq, fixture, load_fixture, test

from scratchpad.paired_situations import dual as app
from scratchpad.paired_situations import dual_sqlite as sqlite


@fixture
async def database() -> AsyncGenerator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.UserRow)})
        yield connected


@test(mark="medium")
async def registration_returns_an_explicit_public_response() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        user = await app.create_user(transaction, "ada@example.com")
    assert_eq(app.public_user(user), app.PublicUser(email="ada@example.com", user_id=1))


@test(mark="fast")
def complete_counter_contains_real_values() -> None:
    counter = app.complete_counter(42, 3)
    assert_eq((counter.counter_id, counter.count), (42, 3))


@test(mark="fast")
def omitted_generated_input_stays_unavailable() -> None:
    pending = app.pending_counter()
    assert_eq(pending.count is app.OMITTED, True)


@test(mark="medium")
async def settings_insert_distinguishes_defaults_from_null() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.SettingsRow)})
        async with connected.transaction() as transaction:
            settings = await app.create_settings(transaction, 1, "UTC", None)
    assert_eq(
        (
            settings.nickname,
            settings.enabled,
            settings.note,
            settings.digest_hour,
            settings.locale,
        ),
        (None, True, None, 9, None),
    )


@test(mark="medium")
async def post_join_projects_author_email() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.UserRow, app.PostRow)})
        async with connected.transaction() as transaction:
            user = await app.create_user(transaction, "ada@example.com")
            await app.create_post(transaction, user.user_id, "Notes")
        async with connected.transaction() as transaction:
            emails = await app.author_emails(transaction)
    assert_eq(emails, ["ada@example.com"])


@test(mark="medium")
async def deleting_parent_sets_reply_reference_to_null() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.CommentRow)})
        async with connected.transaction() as transaction:
            await app.create_comment(transaction, 1, None, "root")
            await app.create_comment(transaction, 2, 1, "reply")
        async with connected.transaction() as transaction:
            await app.delete_comment(transaction, 1)
        async with connected.transaction() as transaction:
            parents = await transaction.fetch_all(
                sqlite.select(app.CommentRow.parent_id).all()
            )
    assert_eq(parents, [None])


@test(mark="medium")
async def mutual_reference_tracks_changed_employee_identity() -> None:
    assert_eq(await app.mutual_foreign_keys(), [20])


@test(mark="medium")
async def large_order_materializes_generated_fields() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.OrderRow)})
        async with connected.transaction() as transaction:
            order = await app.create_order(transaction)
    assert_eq(
        (order.order_id, order.revision, order.metadata), (1, 1, {"channel": "web"})
    )


@test(mark="fast")
def input_methods_use_only_available_fields() -> None:
    from decimal import Decimal

    pending = app.sample_order()
    assert_eq((pending.total(), pending.is_paid()), (Decimal(15), False))


@test(mark="medium")
async def complete_method_uses_generated_identity() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.OrderRow)})
        async with connected.transaction() as transaction:
            order = await app.create_order(transaction)
    assert_eq(app.order_summary(order), ("7/1", "15.0", False))


@test(mark="medium")
async def generic_insert_executes_with_correct_runtime_row() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.CounterRow)})
        async with connected.transaction() as transaction:
            counter = await app.execute_write(
                transaction, app.insert_generic(app.pending_counter())
            )
    assert_eq(
        (type(counter), counter.counter_id, counter.count), (app.CounterRow, 1, 0)
    )


@test(mark="medium")
async def settings_upsert_preserves_unlisted_digest_hour() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.SettingsRow)})
        async with connected.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    app.Settings(
                        user_id=1, timezone="UTC", nickname="Ada", digest_hour=18
                    )
                )
            )
        async with connected.transaction() as transaction:
            settings = await app.save_settings(transaction, 1, "Europe/Paris")
    assert_eq(
        (settings.timezone, settings.digest_hour, settings.nickname),
        ("Europe/Paris", 18, "Ada"),
    )


@test(mark="medium")
async def profile_patch_writes_explicit_null() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        user = await app.create_user(transaction, "ada@example.com")
        await app.patch_user(transaction, user.user_id, {"display_name": "Ada"})
    async with connected.transaction() as transaction:
        patched = await app.patch_user(
            transaction, user.user_id, {"display_name": None}
        )
    assert_eq(patched.display_name if patched else "missing", None)


@test(mark="medium")
async def profile_patch_omission_preserves_existing_name() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        user = await app.create_user(transaction, "ada@example.com")
        await app.patch_user(transaction, user.user_id, {"display_name": "Ada"})
    async with connected.transaction() as transaction:
        patched = await app.patch_user(transaction, user.user_id, {})
    assert_eq(patched.display_name if patched else "missing", "Ada")


@test(mark="medium")
async def optional_lookup_returns_none_for_missing_id() -> None:
    connected = await load_fixture(database())
    async with connected.transaction() as transaction:
        user = await app.fetch_user(transaction, app.UserId(999))
    assert_eq(user, None)


@test(mark="medium")
async def post_insert_rejects_missing_author() -> None:
    from snekql import sqlite as native
    from snektest import assert_raises

    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.UserRow, app.PostRow)})
        with assert_raises(native.ExecutionError):
            async with connected.transaction() as transaction:
                await app.create_post(transaction, app.UserId(999), "orphan")


@test(mark="medium")
async def fresh_settings_save_materializes_sql_default() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as connected:
        await connected.migrate({"001": sqlite.scaffold(app.SettingsRow)})
        async with connected.transaction() as transaction:
            settings = await app.save_settings(transaction, 1, "UTC")
    assert_eq(settings.digest_hour, 9)
