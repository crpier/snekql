"""Backend-neutral semantic schema shapes and drift diffing.

Schema verification compares the *shape* a model expects against the *shape* a
live table actually has, rather than comparing rendered DDL strings. Each
backend reads its own catalog (SQLite ``PRAGMA``, MariaDB ``INFORMATION_SCHEMA``)
into the same :class:`TableShape`, so a table legitimately produced or evolved
by migrations is recognized as matching whenever it is semantically equal,
regardless of cosmetic DDL differences (identifier quoting, whitespace, column
or index ordering).

When shapes differ, :func:`diff_table_shapes` reports each divergence naming the
specific table, column, index, or foreign key so a migration author can act on
it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from snekql._check_catalog import CheckShape, normalize_check
from snekql._checks import CheckExpression
from snekql._schema_verification import SchemaVerificationFact
from snekql._server_defaults import LiteralDefaultShape, compare_literal_default

_COMMON_LIMITS = (
    (
        "table.check_constraints",
        "CHECK verification covers declared names and supported expressions only; unmanaged checks, data, and enforcement settings are not certified",
    ),
    ("columns.generated_expressions", "Generated-column expressions are not inspected"),
    ("table.triggers", "Triggers are not inspected"),
    ("table.views", "Views and dependent views are not inspected"),
    ("table.data", "Stored data is not inspected"),
    (
        "table.other_options",
        "Table options beyond the normalized storage-option tokens are not inspected",
    ),
    (
        "primary_key.structure",
        "Only per-column membership is compared; complete primary-key ordering and grouping are not certified",
    ),
    ("foreign_keys.names", "Foreign-key constraint names are not compared"),
    ("foreign_keys.match", "Foreign-key MATCH semantics are not inspected"),
    ("foreign_keys.deferral", "Foreign-key deferral properties are not inspected"),
    (
        "indexes.expressions",
        "Index expressions are not compared for semantic equivalence",
    ),
    (
        "indexes.predicates",
        "Partial-index verification covers declared supported structure only, not arbitrary equivalence or optimizer index selection",
    ),
    ("indexes.sort_direction", "Index-column sort direction is not inspected"),
    ("indexes.collations", "Index-column collation overrides are not inspected"),
)
"""Stable limitation codes, not observations about objects present in a catalog."""


@dataclass(frozen=True)
class ColumnShape:
    """Semantic column shape with backend-specific facts normalized when exposed."""

    name: str
    storage_type: str
    nullable: bool
    primary_key: bool
    auto_increment: bool
    server_default: str | LiteralDefaultShape | None
    collation: str | None
    datetime_precision: int | None = None
    unsigned: bool | None = None


@dataclass(frozen=True)
class IndexShape:
    """Semantic index shape including backend-specific completeness and type."""

    name: str
    column_names: tuple[str, ...]
    unique: bool
    partial: bool | None = False
    prefix_lengths: tuple[int | None, ...] | None = None
    index_type: str | None = None
    where: CheckExpression | None = None


@dataclass(frozen=True)
class ForeignKeyShape:
    """Semantic foreign-key shape compared by local column, target, and actions.

    `on_delete`/`on_update` hold the normalized referential action. An unset
    action carries `"NO ACTION"`; MariaDB's equivalent `"RESTRICT"` catalog
    value is normalized to the same token. Constraint IDs and positions retain
    grouping for separate ordered-group comparison; scalar equality ignores them.
    """

    column_name: str
    target_table: str
    target_column: str
    on_delete: str = "NO ACTION"
    on_update: str = "NO ACTION"
    constraint_id: str | None = field(default=None, compare=False)
    position: int = field(default=0, compare=False)


@dataclass(frozen=True)
class TableShape:
    """A table's full semantic shape, as expected by a model or read live.

    ``storage_options`` carries backend-specific table-level facts compared as a
    set of tokens (SQLite ``STRICT``; MariaDB ``ENGINE=InnoDB``), so each backend
    keeps its own integrity requirements without a bespoke comparison path.
    """

    table_name: str
    columns: tuple[ColumnShape, ...]
    indexes: tuple[IndexShape, ...]
    foreign_keys: tuple[ForeignKeyShape, ...]
    storage_options: tuple[str, ...]
    checks: tuple[CheckShape, ...] | None = None


class _TableComparison:
    """Record structured evidence at the same decisions that produce legacy drift."""

    def __init__(self, table_name: str) -> None:
        self.table_name: str = table_name
        self.facts: list[SchemaVerificationFact] = []

    def check(
        self, kind: str, object_name: str | None, *, matches: bool, detail: str
    ) -> bool:
        self.facts.append(
            SchemaVerificationFact(
                table_name=self.table_name,
                object_name=object_name,
                kind=kind,
                status="matched" if matches else "drift",
                detail=detail,
            )
        )
        return matches


def _diff_storage_options(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
    comparison: _TableComparison,
) -> None:
    if not comparison.check(
        "table.storage_options",
        None,
        matches=expected.storage_options == actual.storage_options,
        detail=f"storage options expected {list(expected.storage_options)}, found {list(actual.storage_options)}",
    ):
        message = (
            "table storage options differ: "
            f"expected {list(expected.storage_options)}, "
            f"found {list(actual.storage_options)}"
        )
        issues.append(message)


def _column_differences(
    expected: ColumnShape,
    actual: ColumnShape,
    comparison: _TableComparison,
) -> list[str]:
    properties = (
        (
            "type",
            expected.storage_type,
            actual.storage_type,
            f"type expected {expected.storage_type!r}, found {actual.storage_type!r}",
        ),
        (
            "nullable",
            expected.nullable,
            actual.nullable,
            f"nullable expected {expected.nullable}, found {actual.nullable}",
        ),
        (
            "primary_key",
            expected.primary_key,
            actual.primary_key,
            f"primary key expected {expected.primary_key}, found {actual.primary_key}",
        ),
        (
            "auto_increment",
            expected.auto_increment,
            actual.auto_increment,
            f"auto-increment expected {expected.auto_increment}, found {actual.auto_increment}",
        ),
        (
            "server_default",
            expected.server_default,
            actual.server_default,
            f"server default expected {expected.server_default!r}, found {actual.server_default!r}",
        ),
        (
            "collation",
            expected.collation,
            actual.collation,
            f"collation expected {expected.collation!r}, found {actual.collation!r}",
        ),
        (
            "datetime_precision",
            expected.datetime_precision,
            actual.datetime_precision,
            f"datetime precision expected {expected.datetime_precision}, found {actual.datetime_precision}",
        ),
        (
            "unsigned",
            expected.unsigned,
            actual.unsigned,
            f"unsigned expected {expected.unsigned}, found {actual.unsigned}",
        ),
    )
    differences: list[str] = []
    for kind, expected_value, actual_value, detail in properties:
        if kind == "server_default" and isinstance(expected_value, LiteralDefaultShape):
            status, default_detail = compare_literal_default(
                expected_value, actual_value, nullable=actual.nullable
            )
            comparison.facts.append(
                SchemaVerificationFact(
                    comparison.table_name,
                    expected.name,
                    "column.server_default",
                    status,
                    default_detail,
                )
            )
            if status == "drift":
                differences.append(default_detail)
            if (
                expected_value.backend == "mariadb"
                and expected_value.value is None
                and actual_value is None
                and actual.nullable
            ):
                comparison.facts.append(
                    SchemaVerificationFact(
                        comparison.table_name,
                        expected.name,
                        "column.server_default_explicitness",
                        "unchecked",
                        "MariaDB does not distinguish implicit NULL from an explicit DEFAULT NULL clause",
                    )
                )
            continue
        # Missing optional metadata is not evidence of a successful inspection.
        if (
            kind in {"collation", "datetime_precision", "unsigned"}
            and expected_value is None
            and actual_value is None
        ):
            continue
        if not comparison.check(
            f"column.{kind}",
            expected.name,
            matches=expected_value == actual_value,
            detail=detail,
        ):
            differences.append(detail)
    return differences


def _diff_columns(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
    comparison: _TableComparison,
) -> None:
    expected_by_name = {column.name: column for column in expected.columns}
    actual_by_name = {column.name: column for column in actual.columns}
    issues.extend(
        f"column {name!r} is missing from the database table"
        for name in expected_by_name
        if name not in actual_by_name
    )
    issues.extend(
        f"column {name!r} exists in the database but not in the model"
        for name in actual_by_name
        if name not in expected_by_name
    )
    for name in sorted(expected_by_name.keys() | actual_by_name.keys()):
        comparison.check(
            "column.presence",
            name,
            matches=name in expected_by_name and name in actual_by_name,
            detail=(
                f"column {name!r} is present in the model and database"
                if name in expected_by_name and name in actual_by_name
                else f"column {name!r} is missing from the database table"
                if name in expected_by_name
                else f"column {name!r} exists in the database but not in the model"
            ),
        )
    for name, expected_column in expected_by_name.items():
        actual_column = actual_by_name.get(name)
        if actual_column is None:
            continue
        differences = _column_differences(expected_column, actual_column, comparison)
        if differences:
            issues.append(f"column {name!r} differs: {', '.join(differences)}")


def _index_differences(
    expected: IndexShape,
    actual: IndexShape,
    comparison: _TableComparison,
) -> list[str]:
    properties = (
        (
            "columns",
            expected.column_names,
            actual.column_names,
            f"columns expected {list(expected.column_names)}, found {list(actual.column_names)}",
        ),
        (
            "unique",
            expected.unique,
            actual.unique,
            f"uniqueness expected {expected.unique}, found {actual.unique}",
        ),
        (
            "partial",
            expected.partial,
            actual.partial,
            f"partial expected {expected.partial}, found {actual.partial}",
        ),
        (
            "prefix_lengths",
            expected.prefix_lengths,
            actual.prefix_lengths,
            f"prefix lengths expected {list(expected.prefix_lengths or ())}, found {list(actual.prefix_lengths or ())}",
        ),
        (
            "type",
            expected.index_type,
            actual.index_type,
            f"index type expected {expected.index_type!r}, found {actual.index_type!r}",
        ),
    )
    differences: list[str] = []
    for kind, expected_value, actual_value, detail in properties:
        if expected_value is None and actual_value is None:
            continue
        if not comparison.check(
            f"index.{kind}",
            expected.name,
            matches=expected_value == actual_value,
            detail=detail,
        ):
            differences.append(detail)
    if expected.where is not None:
        if actual.partial is None or (actual.partial and actual.where is None):
            comparison.facts.append(
                SchemaVerificationFact(
                    comparison.table_name,
                    expected.name,
                    "index.predicate",
                    "unchecked",
                    "Partial-index predicate is unavailable or outside the supported grammar",
                )
            )
        elif not comparison.check(
            "index.predicate",
            expected.name,
            matches=actual.where is not None
            and normalize_check(expected.where) == normalize_check(actual.where),
            detail="normalized partial-index predicate structure compared",
        ):
            differences.append("partial-index predicate differs")
    return differences


def _diff_indexes(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
    comparison: _TableComparison,
) -> None:
    expected_by_name = {index.name: index for index in expected.indexes}
    actual_by_name = {index.name: index for index in actual.indexes}
    issues.extend(
        f"index {name!r} is missing from the database table"
        for name in expected_by_name
        if name not in actual_by_name
    )
    issues.extend(
        f"index {name!r} exists in the database but not in the model"
        for name in actual_by_name
        if name not in expected_by_name
    )
    for name in sorted(expected_by_name.keys() | actual_by_name.keys()):
        comparison.check(
            "index.presence",
            name,
            matches=name in expected_by_name and name in actual_by_name,
            detail=(
                f"index {name!r} is present in the model and database"
                if name in expected_by_name and name in actual_by_name
                else f"index {name!r} is missing from the database table"
                if name in expected_by_name
                else f"index {name!r} exists in the database but not in the model"
            ),
        )
    for name, expected_index in expected_by_name.items():
        actual_index = actual_by_name.get(name)
        if actual_index is None:
            continue
        differences = _index_differences(expected_index, actual_index, comparison)
        if differences:
            issues.append(f"index {name!r} differs: {', '.join(differences)}")


def _describe_foreign_key(
    foreign_key: ForeignKeyShape,
    *,
    include_default_actions: bool = False,
) -> str:
    description = f"{foreign_key.target_table}.{foreign_key.target_column}"
    if include_default_actions or foreign_key.on_delete != "NO ACTION":
        description += f" ON DELETE {foreign_key.on_delete}"
    if include_default_actions or foreign_key.on_update != "NO ACTION":
        description += f" ON UPDATE {foreign_key.on_update}"
    return description


def _foreign_key_facts(foreign_key: ForeignKeyShape) -> tuple[str, str, str, str]:
    return (
        foreign_key.target_table,
        foreign_key.target_column,
        foreign_key.on_delete,
        foreign_key.on_update,
    )


def _foreign_key_group_counts(
    foreign_keys: tuple[ForeignKeyShape, ...],
) -> Counter[tuple[tuple[str, str, str, str, str], ...]]:
    """Ignore catalog identities while retaining ordered pairs and multiplicity."""
    return Counter(
        tuple((member.column_name, *_foreign_key_facts(member)) for member in group)
        for group in group_foreign_keys(foreign_keys)
    )


def _diff_foreign_keys(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
    comparison: _TableComparison,
) -> None:
    """Match complete per-column multisets before reporting remaining differences."""

    previous_foreign_key_issues = len(issues)
    expected_by_column: defaultdict[str, list[ForeignKeyShape]] = defaultdict(list)
    actual_by_column: defaultdict[str, list[ForeignKeyShape]] = defaultdict(list)
    for foreign_key in expected.foreign_keys:
        expected_by_column[foreign_key.column_name].append(foreign_key)
    for foreign_key in actual.foreign_keys:
        actual_by_column[foreign_key.column_name].append(foreign_key)
    if not expected_by_column and not actual_by_column:
        comparison.check(
            "foreign_key.relationships",
            None,
            matches=True,
            detail="no scalar foreign-key relationships are present in either compared shape",
        )
    for column_name in sorted(expected_by_column.keys() | actual_by_column.keys()):
        previous_issue_count = len(issues)
        remaining_actual = sorted(actual_by_column[column_name], key=_foreign_key_facts)
        remaining_expected: list[ForeignKeyShape] = []
        # Remove exact matches first, one occurrence at a time. A set would
        # hide duplicate constraints, and pairing first could obscure a match.
        for expected_fk in sorted(
            expected_by_column[column_name], key=_foreign_key_facts
        ):
            if expected_fk in remaining_actual:
                remaining_actual.remove(expected_fk)
            else:
                remaining_expected.append(expected_fk)
        paired = min(len(remaining_expected), len(remaining_actual))
        for expected_fk, actual_fk in zip(
            remaining_expected[:paired], remaining_actual[:paired], strict=True
        ):
            issues.append(
                f"foreign key on column {column_name!r} differs: "
                f"expected -> {_describe_foreign_key(expected_fk, include_default_actions=True)}, "
                f"found -> {_describe_foreign_key(actual_fk, include_default_actions=True)}"
            )
        issues.extend(
            f"foreign key on column {column_name!r} -> "
            f"{_describe_foreign_key(expected_fk)} is missing from the "
            "database table"
            for expected_fk in remaining_expected[paired:]
        )
        issues.extend(
            f"foreign key on column {column_name!r} -> "
            f"{_describe_foreign_key(actual_fk)} exists in the database but "
            "not in the model"
            for actual_fk in remaining_actual[paired:]
        )

        differences = issues[previous_issue_count:]
        comparison.check(
            "foreign_key.relationships",
            column_name,
            matches=not differences,
            detail="; ".join(differences)
            if differences
            else "scalar foreign-key relationship multiset matches, including targets and actions",
        )

    expected_groups = _foreign_key_group_counts(expected.foreign_keys)
    actual_groups = _foreign_key_group_counts(actual.foreign_keys)
    group_match = expected_groups == actual_groups
    detail = (
        "ordered foreign-key constraint groups match"
        if group_match
        else f"foreign-key constraint groups differ: expected {sorted(expected_groups.elements())!r}, found {sorted(actual_groups.elements())!r}"
    )
    comparison.check("foreign_keys.grouping", None, matches=group_match, detail=detail)
    if not group_match and len(issues) == previous_foreign_key_issues:
        issues.append(detail)


def _diff_checks(
    expected: TableShape,
    actual: TableShape,
    issues: list[str],
    comparison: _TableComparison,
) -> None:
    """Compare declared names, leaving unreadable and unmanaged expressions explicit."""
    for expected_check in expected.checks or ():
        matches = [
            check for check in actual.checks or () if check.name == expected_check.name
        ]
        if actual.checks is None:
            comparison.facts.append(
                SchemaVerificationFact(
                    expected.table_name,
                    expected_check.name,
                    "check.presence",
                    "unchecked",
                    "CHECK catalog structure could not be inspected",
                )
            )
            continue
        if not comparison.check(
            "check.presence",
            expected_check.name,
            matches=bool(matches),
            detail="declared CHECK is present"
            if matches
            else "declared CHECK is missing",
        ):
            issues.append(f"CHECK constraint {expected_check.name!r} is missing")
            continue
        if len(matches) != 1 or matches[0].expression is None:
            comparison.facts.append(
                SchemaVerificationFact(
                    expected.table_name,
                    expected_check.name,
                    "check.expression",
                    "unchecked",
                    "CHECK expression is unsupported or its name is ambiguous",
                )
            )
            continue
        if not comparison.check(
            "check.expression",
            expected_check.name,
            matches=normalize_check(matches[0].expression)
            == normalize_check(expected_check.expression)
            if expected_check.expression is not None
            else False,
            detail="normalized CHECK expression structure compared",
        ):
            issues.append(
                f"CHECK constraint {expected_check.name!r} expression differs"
            )
    expected_names = {check.name for check in expected.checks or ()}
    unmanaged = Counter(
        check.name for check in actual.checks or () if check.name not in expected_names
    )
    comparison.facts.extend(
        SchemaVerificationFact(
            expected.table_name,
            name,
            "check.unmanaged",
            "unchecked",
            f"{count} undeclared CHECK expression(s) are not compared",
        )
        for name, count in unmanaged.items()
    )


def group_foreign_keys(
    foreign_keys: tuple[ForeignKeyShape, ...],
) -> tuple[tuple[ForeignKeyShape, ...], ...]:
    """Retain constraint membership and pair order independently of catalog names."""
    groups: dict[tuple[str | None, int], list[ForeignKeyShape]] = {}
    for ordinal, foreign_key in enumerate(foreign_keys):
        key = (
            foreign_key.constraint_id,
            ordinal if foreign_key.constraint_id is None else 0,
        )
        groups.setdefault(key, []).append(foreign_key)
    return tuple(
        tuple(sorted(group, key=lambda member: member.position))
        for group in groups.values()
    )


def compare_table_shapes(
    expected: TableShape, actual: TableShape
) -> tuple[tuple[str, ...], tuple[SchemaVerificationFact, ...]]:
    """Return legacy drift diagnostics and structured evidence from one comparison."""
    issues: list[str] = []
    comparison = _TableComparison(expected.table_name)
    comparison.check(
        "table.presence",
        None,
        matches=True,
        detail="catalog entry exists for the requested table name",
    )
    _diff_storage_options(expected, actual, issues, comparison)
    _diff_columns(expected, actual, issues, comparison)
    _diff_indexes(expected, actual, issues, comparison)
    _diff_foreign_keys(expected, actual, issues, comparison)
    _diff_checks(expected, actual, issues, comparison)
    comparison.facts.extend(
        SchemaVerificationFact(
            table_name=expected.table_name,
            object_name=None,
            kind=kind,
            status="unchecked",
            detail=detail,
        )
        for kind, detail in _COMMON_LIMITS
    )
    return tuple(issues), tuple(comparison.facts)


def diff_table_shapes(expected: TableShape, actual: TableShape) -> tuple[str, ...]:
    """Report semantic drift while preserving the original diagnostic interface."""
    return compare_table_shapes(expected, actual)[0]
