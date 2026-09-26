"""Locking clauses preserve query shape and fail closed on unsupported forms."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Job[S = mariadb.Pending](mariadb.Model[S]):
    """A queue entry with explicit claim state."""

    __row_type__: ClassVar[mariadb.ReadType[Job[mariadb.Row]]]

    id: Job.Col[int] = mariadb.Integer(primary_key=True)
    status: Job.Col[str] = mariadb.Text()


@test(mark="fast")
def locking_select_compiles_after_pagination() -> None:
    """Lock options do not reorder or replace ordinary bindings."""
    compiled = (
        mariadb.select(Job.id)
        .where(Job.status.eq("pending"))
        .order_by(Job.id.asc())
        .limit(1)
        .offset(2)
        .for_update(wait="skip_locked")
        .compile()
    )
    assert_eq(
        compiled.sql,
        "SELECT `id` FROM `job` WHERE (`status` = %s) ORDER BY `id` ASC "
        "LIMIT %s OFFSET %s FOR UPDATE SKIP LOCKED",
    )
    assert_eq(compiled.params, ("pending", 1, 2))


@test(mark="fast")
def sqlite_rejects_locking_clauses() -> None:
    """SQLite never silently drops unsupported row-locking intent."""

    class LocalJob[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[LocalJob[sqlite.Row]]]
        id: LocalJob.Col[int] = sqlite.Integer(primary_key=True)

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(LocalJob).all().for_update().compile()


@test(
    [
        Param(value="distinct", name="distinct"),
        Param(value="aggregate", name="aggregate"),
        Param(value="grouped", name="grouped"),
        Param(value="joined", name="joined"),
    ],
    mark="fast",
)
def locking_rejects_unsupported_shapes(shape: str) -> None:
    """Lock scope stays explicit while grouped and multi-source forms are deferred."""

    class Peer:
        pass

    peer = mariadb.alias(Job, Peer, name="peer")
    with assert_raises(mariadb.QueryCompilationError):
        if shape == "distinct":
            mariadb.select(Job).all().for_update().distinct().compile()
        elif shape == "aggregate":
            mariadb.select(Job.count_all()).all().for_update().compile()
        elif shape == "grouped":
            mariadb.select(Job.id).all().group_by(Job.id).for_update().compile()
        else:
            mariadb.select(Job).join(
                peer, on=Job.id.eq_col(peer.column(Job.id))
            ).all().for_update().compile()


@test(
    [
        Param(value="exists", name="exists"),
        Param(value="scalar", name="scalar"),
        Param(value="membership", name="membership"),
    ],
    mark="fast",
)
def locking_subqueries_are_rejected(kind: str) -> None:
    """Every nested compilation path rejects an inner locking clause."""
    inner = mariadb.select(Job.id).where(Job.id.gt(0)).for_update()
    with assert_raises(mariadb.QueryCompilationError):
        if kind == "exists":
            mariadb.select(Job).where(mariadb.exists(inner)).compile()
        elif kind == "scalar":
            mariadb.select(Job.id, mariadb.scalar(inner)).all().compile()
        else:
            mariadb.select(Job).where(Job.id.in_subquery(inner)).compile()


@test(mark="fast")
def locking_rejects_aggregate_ordering() -> None:
    """An aggregate in ORDER BY is still an aggregate query, even without projection."""
    with assert_raises(mariadb.QueryCompilationError):
        mariadb.select(Job.id).all().order_by(
            Job.id.count().desc()
        ).for_update().compile()


class JobSummary(BaseModel):
    """A named claim result retains its application contract."""

    id: int
    status: str


@test(mark="fast")
def locking_options_do_not_mutate_original_query() -> None:
    """Reconfiguring wait behavior creates another immutable query."""
    original = mariadb.select(Job.id).all()
    nowait = original.for_update(wait="nowait")
    blocking = nowait.for_update()
    assert_eq(original.compile().sql, "SELECT `id` FROM `job`")
    assert_eq(nowait.compile().sql, "SELECT `id` FROM `job` FOR UPDATE NOWAIT")
    assert_eq(blocking.compile().sql, "SELECT `id` FROM `job` FOR UPDATE")


@test(mark="fast")
def locking_named_alias_projection_retains_labels() -> None:
    """A query-only alias still identifies one physical table for locking."""

    class ClaimRole:
        pass

    jobs = mariadb.alias(Job, ClaimRole, name="jobs")
    compiled = (
        mariadb.select(jobs)
        .project(JobSummary, id=jobs.column(Job.id), status=jobs.column(Job.status))
        .all()
        .for_update()
        .compile()
    )
    assert_eq(
        compiled.sql,
        "SELECT `id` AS `id`, `status` AS `status` FROM `job` AS `jobs` FOR UPDATE",
    )


@test(mark="fast")
def locking_requires_explicit_row_scope() -> None:
    """Lock intent cannot substitute for all() or where()."""
    with assert_raises(mariadb.QueryCompilationError):
        mariadb.select(Job).for_update().compile()


@test(mark="fast")
def locking_wait_argument_is_strict() -> None:
    """Only the reviewed wait choices are accepted, not SQL text or booleans."""
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.select(Job).all().for_update(wait="NOWAIT")  # ty: ignore[invalid-argument-type]
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.select(Job).all().for_update(wait=True)  # ty: ignore[invalid-argument-type]


if TYPE_CHECKING:

    def job_claim_query() -> mariadb.ClosedRead[Job[mariadb.Row]]:
        """Helpers retain named result types and executable readiness."""
        return mariadb.ready(
            mariadb.select(Job)
            .where(Job.status.eq("pending"))
            .for_update(wait="skip_locked")
        )

    async def check_locking_types(
        transaction: mariadb.Transaction, other: sqlite.Transaction
    ) -> None:
        """Lock modifiers preserve row shape, backend identity, and completeness."""
        assert_type(
            await transaction.fetch_all(job_claim_query()), list[Job[mariadb.Row]]
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(Job.id).all().for_update()),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.select(Job.id, Job.status).all().for_update()
            ),
            list[tuple[int, str]],
        )
        named = (
            mariadb.select(Job)
            .project(JobSummary, id=Job.id, status=Job.status)
            .all()
            .for_update()
        )
        assert_type(await transaction.fetch_one_or_none(named), JobSummary | None)
        await transaction.fetch_all(mariadb.select(Job).for_update())  # ty: ignore[no-matching-overload]
        await other.fetch_all(job_claim_query())  # ty: ignore[no-matching-overload]
