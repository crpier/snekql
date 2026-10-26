"""Distinct typing challenges and session-scoped real batch assessments."""

import sys
from collections.abc import AsyncGenerator
from json import dumps

from anyio import Path, TemporaryDirectory, run_process
from snektest import fixture

from tests.typing_assessment import TypingAssessment

NESTED_EXPRESSIONS: tuple[tuple[str, str, str], ...] = (
    *(
        (
            operator,
            f"Account.number.{operator}(foreign.scalar(remote))",
            "no-matching-overload",
        )
        for operator in (
            "eq_col",
            "ne_col",
            "gt_col",
            "gte_col",
            "lt_col",
            "lte_col",
        )
    ),
    (
        "not-in",
        "Account.number.not_in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "arithmetic",
        "Account.number.add(1).in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "aggregate",
        "Account.number.count().in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "count-all",
        "Account.count_all().in_subquery(remote)",
        "invalid-argument-type",
    ),
    ("fk", "Invoice.account.in_subquery(remote)", "invalid-argument-type"),
    (
        "generated",
        "Invoice.generated.in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "alias",
        "aliased.column(Account.number).in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "cte",
        "derived.column(token).in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "compound",
        "compound.column(token).in_subquery(remote)",
        "invalid-argument-type",
    ),
    (
        "cte-foreign-token",
        "derived.column(Foreign.number.label('number'))",
        "no-matching-overload",
    ),
    (
        "compound-foreign-token",
        "compound.column(Foreign.number.label('number'))",
        "no-matching-overload",
    ),
    (
        "not-exists",
        "database.select(Account).where(foreign.not_exists(remote))",
        "invalid-argument-type",
    ),
    (
        "inverted",
        "database.select(Account).where(~foreign.exists(remote))",
        "invalid-argument-type",
    ),
    (
        "and-right",
        "Account.number.eq(1) & foreign.exists(remote)",
        "unsupported-operator",
    ),
    (
        "and-left",
        "foreign.exists(remote) & Account.number.eq(1)",
        "unsupported-operator",
    ),
    (
        "or-right",
        "Account.number.eq(1) | foreign.exists(remote)",
        "unsupported-operator",
    ),
    (
        "or-left",
        "foreign.exists(remote) | Account.number.eq(1)",
        "unsupported-operator",
    ),
    (
        "delete",
        "database.delete(Account).where(foreign.exists(remote))",
        "invalid-argument-type",
    ),
    (
        "update",
        "database.update(Account).set(Account.number.to(1)).where(foreign.exists(remote))",
        "no-matching-overload",
    ),
    (
        "having",
        "database.select(Account.number.count()).having(foreign.exists(remote))",
        "invalid-argument-type",
    ),
    (
        "join",
        "database.select(Account).join(Invoice, on=foreign.exists(remote))",
        "no-matching-overload",
    ),
    (
        "read-only",
        "column(Account.number).eq(1) & foreign.exists(remote)",
        "unsupported-operator",
    ),
    (
        "predicate-helper",
        "negate(foreign.exists(remote))",
        "invalid-argument-type",
    ),
    (
        "scalar-helper",
        "wrong: database.Scalar[Never, int | None, int] = foreign.scalar(remote)",
        "invalid-assignment",
    ),
    (
        "named-scalar",
        "database.select(Account).project(Result, number=foreign.scalar(remote))",
        "invalid-argument-type",
    ),
    (
        "named-label",
        "database.select(Account).project(Result, number=foreign.scalar(remote).label('number'))",
        "invalid-argument-type",
    ),
    (
        "named-literal",
        "database.select(Account).project(Result, number=foreign.literal(1).label('number'))",
        "invalid-argument-type",
    ),
    *(
        (
            f"projection-{width}",
            "database.select("
            + "Account.number, " * (width - 1)
            + "foreign.scalar(remote))",
            "invalid-argument-type",
        )
        for width in range(2, 9)
    ),
)


TEMPORAL_EXPRESSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "raw-datetime",
        "Event.instant.eq(datetime(2026, 1, 1, tzinfo=UTC))",
        "invalid-argument-type",
    ),
    ("column", "Event.instant.eq_col(Event.civil)", "no-matching-overload"),
    (
        "membership",
        "Event.instant.in_subquery(database.select(Event.civil))",
        "invalid-argument-type",
    ),
    (
        "readonly",
        "instant_column(Event.instant).eq(civil)",
        "invalid-argument-type",
    ),
    ("assignment", "Event.instant.to(civil)", "no-matching-overload"),
    ("cte", "derived.column(token).eq(civil)", "invalid-argument-type"),
    (
        "alias",
        "aliased.column(Event.instant).eq(civil)",
        "invalid-argument-type",
    ),
    ("aggregate", "Event.instant.min().eq(civil)", "invalid-argument-type"),
    (
        "scalar",
        "Event.instant.eq_col(database.scalar(database.select(Event.civil)))",
        "no-matching-overload",
    ),
    ("constructor", "database.UtcDatetime(civil)", "invalid-argument-type"),
    ("result", "wrong: database.LocalDatetime = instant", "invalid-assignment"),
)


async def assess_variants(
    case: str, variants: tuple[tuple[str, str, str], ...]
) -> TypingAssessment:
    """Each expression keeps independent paired files and backend ownership."""
    positive = await Path(f"typing_probes/{case}.positive.py.txt").read_text()
    requests = [
        {
            "name": expression,
            "backend": backend,
            "positive": positive,
            "negative": f"\n\n{expression}  # expect-error\n",
        }
        for _, expression, _ in variants
        for backend in ("sqlite", "mariadb")
    ]
    async with TemporaryDirectory(prefix="typing-variants-") as directory:
        manifest = Path(directory) / "requests.json"
        await manifest.write_text(dumps({"schema_version": 1, "cases": requests}))
        completed = await run_process(
            [
                sys.executable,
                "scripts/check_typing_compatibility.py",
                "--manifest",
                str(manifest),
            ],
            check=False,
        )
    return TypingAssessment(completed)


@fixture(scope="session")
async def provide_nested_assessment() -> AsyncGenerator[TypingAssessment]:
    """Only this immutable nested-expression corpus shares an assessment."""
    yield await assess_variants("nested-helper-family", NESTED_EXPRESSIONS)


@fixture(scope="session")
async def provide_temporal_assessment() -> AsyncGenerator[TypingAssessment]:
    """Temporal requests do not borrow static or nested-expression evidence."""
    yield await assess_variants("temporal-domains", TEMPORAL_EXPRESSIONS)
