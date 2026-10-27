"""Model-derived stages compose through the authoring seam, not caller state stitching."""

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_check_additions import Checked
from tests.experimental.test_migration_contraction import Contracted, Expanded, Original
from tests.experimental.test_migration_defaulted_additions import Added, Initial
from tests.experimental.test_migration_indexes import Indexed
from tests.experimental.test_migration_nullability import Required


@test(mark="fast")
def one_revision_advances_through_backfill_to_final_models() -> None:
    """Keep real lineage and the checkpoint contract while generating the next stage."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    expansion = m.generate("002", [Expanded], backend="sqlite", previous=first).then(
        m.Checkpoint(name="fill")
    )
    digest = m.contract_digest(expansion, point="fill")
    route = expansion.then(
        m.DataChange.from_query(
            sqlite.update(Expanded).set(Expanded.role.to("user")).all(),
            checkpoint="fill",
            contract_digest=digest,
        ),
        m.DataChange.from_query(
            sqlite.update(Expanded)
            .set(Expanded.role.to("admin"))
            .where(Expanded.is_admin.eq(True)),
            checkpoint="fill",
            contract_digest=digest,
        ),
    ).advance(
        [Contracted],
        removals=(m.DropColumn(table_name="account", column_name="is_admin"),),
    )
    package = m.Package.load(m.compile(route).dump())
    assert_eq(
        (package.draft.revision, package.draft.predecessor), ("002", first.digest)
    )
    assert_eq(package.draft.before, first.target)
    assert_eq(m.contract_digest(route, point="fill"), digest)
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("id", "role"))
    assert_eq(package.target.tables[0].columns[1].nullable, False)
    assert_eq(expansion.target.tables[0].columns[2].nullable, True)


@test(mark="fast")
def missing_removal_decisions_refuse_without_changing_the_existing_route() -> None:
    """Advance is an all-or-nothing authoring stage, not permission to infer destruction."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    route = m.generate("002", [Expanded], backend="sqlite", previous=first)
    before = m.compile(route).dump()
    with assert_raises(m.PackageError) as error:
        route.advance([Contracted])
    assert "explicit DropColumn required" in str(error.exception)
    assert_eq(m.compile(route).dump(), before)
    with assert_raises(m.PackageError):
        route.advance(
            [Contracted],
            removals=(m.DropColumn(table_name="account", column_name="unknown"),),
        )
    assert_eq(m.compile(route).dump(), before)


@test(mark="fast")
def unresolved_existing_stage_cannot_be_hidden_by_a_later_target() -> None:
    """A later target cannot clear or retroactively resolve earlier decisions."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    unresolved = m.generate("002", [Contracted], backend="sqlite", previous=first)
    with assert_raises(m.PackageError) as error:
        unresolved.advance([Expanded])
    assert "resolve the current stage" in str(error.exception)
    assert "explicit DropColumn required" in str(error.exception)
    resolved = unresolved.resolve(
        m.DropColumn(table_name="account", column_name="is_admin")
    )
    assert_eq(m.compile(resolved.advance([Contracted])).draft.revision, "002")


@test(mark="fast")
def dropping_an_index_in_a_later_stage_does_not_rewrite_earlier_checkpoints() -> None:
    """Stage-local resolution stays after earlier index creation and typed contract."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    prefix = m.generate("002", [Indexed], backend="sqlite", previous=first).then(
        m.Checkpoint(name="indexed")
    )
    digest = m.contract_digest(prefix, point="indexed")
    route = prefix.advance(
        [Required], removals=(m.DropIndex(table_name="entries", index_name="by_value"),)
    )
    package = m.compile(route)
    assert_eq(package.version, 6)
    assert_eq(
        package.statements,
        (
            'CREATE UNIQUE INDEX "by_value" ON "entries" ("value")',
            "DROP INDEX `by_value`",
        ),
    )
    assert_eq(m.contract_digest(route, point="indexed"), digest)
    assert_eq(package.target.tables[0].indexes, ())


@test(mark="fast")
def later_check_removal_stays_after_its_creation_and_checkpoint() -> None:
    """Resolving a new stage must not prepend DROP CHECK ahead of earlier work."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    prefix = m.generate("002", [Checked], backend="sqlite", previous=first).then(
        m.Checkpoint(name="checked")
    )
    digest = m.contract_digest(prefix, point="checked")
    route = prefix.advance(
        [Required],
        removals=(m.DropCheck(table_name="entries", check_name="ck_nonnegative"),),
    )
    package = m.compile(route)
    assert_eq(package.version, 8)
    assert_eq(m.contract_digest(route, point="checked"), digest)
    assert package.contractions[0] is not None and package.contractions[0].added_checks
    assert package.contractions[1] is not None and package.contractions[
        1
    ].removed_checks == ("ck_nonnegative",)


@test(mark="fast")
def handoff_remains_explicit_and_does_not_authorize_same_route_recreation() -> None:
    """Advancing desired model scope cannot turn relinquishment into DROP or adoption."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    route = m.generate("002", [Required], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        route.advance([])
    handed = route.advance([], removals=(m.RelinquishTable(table_name="entries"),))
    package = m.compile(handed)
    assert_eq(package.statements, ())
    assert_eq(package.target.tables, ())
    with assert_raises(m.PackageError) as error:
        handed.advance([Required])
    assert "explicit adoption" in str(error.exception)


@test(mark="fast")
def advance_validates_existing_typed_work_before_generating_a_new_shape() -> None:
    """A newer stage cannot launder stale data contracts, even if physical DML would work."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    draft = m.generate("002", [Expanded], backend="sqlite", previous=first).then(
        m.Checkpoint(name="fill")
    )
    draft = draft.then(
        m.DataChange.from_query(
            sqlite.update(Expanded).set(Expanded.role.to("user")).all(),
            checkpoint="fill",
            contract_digest="0" * 64,
        )
    )
    with assert_raises(m.PackageError) as error:
        draft.advance(
            [Contracted],
            removals=(m.DropColumn(table_name="account", column_name="is_admin"),),
        )
    assert "stale or mismatched intermediate contract" in str(error.exception)


@test(mark="fast")
def defaulted_addition_policy_remains_an_explicit_stage_choice() -> None:
    """Advancing must not infer old-row backfills from a server default."""
    first = m.compile(m.generate("001", [Initial], backend="sqlite"))
    draft = m.generate("002", [Initial], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        draft.advance([Added])
    stage = draft.advance([Added], defaulted_additions="leave_null")
    package = m.compile(stage)
    assert_eq(package.version, 3)
    assert isinstance(stage.operations[0], m.AddColumn)
    assert "DEFAULT" not in stage.operations[0].column.definition
    assert isinstance(stage.operations[1], m.ChangeDefault)
    assert "DEFAULT 7" in stage.operations[1].column.definition


@test(mark="fast")
def typed_work_cannot_be_reused_after_advancing_past_its_checkpoint_shape() -> None:
    """Keeping historical source does not grant permission to run it after contraction."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    prefix = m.generate("002", [Expanded], backend="sqlite", previous=first).then(
        m.Checkpoint(name="fill")
    )
    work = m.DataChange.from_query(
        sqlite.update(Expanded).set(Expanded.role.to("user")).all(),
        checkpoint="fill",
        contract_digest=m.contract_digest(prefix, point="fill"),
    )
    final = prefix.then(work).advance(
        [Contracted],
        removals=(m.DropColumn(table_name="account", column_name="is_admin"),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(final.then(work))
    assert "stale or mismatched intermediate contract" in str(error.exception)
