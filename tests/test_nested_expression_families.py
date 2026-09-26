"""Backend identity survives public nested-expression composition."""

import sys
from json import loads

from anyio import Path, run_process
from snektest import Param, assert_eq, assert_true, load_fixture, test

from tests.test_typing_compatibility import provide_probe_checkout


@test(
    [Param(backend, name=backend) for backend in ("sqlite", "mariadb")],
    [
        Param((expression, rule), name=name)
        for name, expression, rule in (
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
                "database.select(Account.number.count()).all().having(foreign.exists(remote))",
                "invalid-argument-type",
            ),
            (
                "join",
                "database.select(Account).join(Invoice, on=foreign.exists(remote)).all()",
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
                "database.select(Account).all().project(Result, number=foreign.scalar(remote))",
                "invalid-argument-type",
            ),
            (
                "named-label",
                "database.select(Account).all().project(Result, number=foreign.scalar(remote).label('number'))",
                "invalid-argument-type",
            ),
            (
                "named-literal",
                "database.select(Account).all().project(Result, number=foreign.literal(1).label('number'))",
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
    ],
    mark="slow",
)
async def nested_expression_rejects_foreign_family(
    backend: str, challenge: tuple[str, str]
) -> None:
    """One invalid composition fails beside exact public helper controls."""
    root = await load_fixture(provide_probe_checkout())
    expression, rule = challenge
    case = "nested-helper-family"
    await (root / "typing_probes" / f"{case}.positive.py.txt").write_text(
        await Path(f"typing_probes/{case}.positive.py.txt").read_text()
    )
    await (root / "typing_probes" / f"{case}.negative.py.txt").write_text(
        f"\n\n{expression}  # expect-error\n"
    )

    completed = await run_process(
        [
            sys.executable,
            str(root / "scripts/check_typing_compatibility.py"),
            "--case",
            case,
            "--backend",
            backend,
        ],
        check=False,
    )

    report = loads(completed.stdout)
    assert_eq(len(report["cases"]), 1)
    observed = report["cases"][0]
    assert_eq(observed["positive_errors"], [])
    assert_eq(len(observed["negative_errors"]), 1)
    assert_eq(observed["negative_errors"][0]["line"], observed["expected_line"])
    assert_eq(observed["negative_errors"][0]["rule"], rule)
    assert_true(observed["conforms"])
    assert_eq(completed.returncode, 0, msg=completed.stderr.decode())
