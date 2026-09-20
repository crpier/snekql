"""Backend-neutral schema verification flow shared by Backend Runtime Adapters.

Verification is an explicit, partial, structural check (see ADR 0008): it
inspects the live shape of each Table Model's table and diffs it against the
expected shape, reporting Schema Drift under the active Schema Policy. It never
creates anything -- migrations are the sole schema-creation authority (ADR 0007).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from snekql._schema_plan import (
    build_schema_plan,
)
from snekql._schema_plan import (
    validate_schema_policy as validate_planned_schema_policy,
)
from snekql._schema_shape import compare_table_shapes
from snekql._schema_verification import (
    SchemaDriftIssue,
    SchemaVerificationFact,
    SchemaVerificationResult,
)
from snekql.errors import SchemaVerificationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from snekql._schema_plan import PlannedModel
    from snekql._schema_shape import TableShape
    from snekql.model import Table
    from snekql.storage import SchemaPolicy

logger = logging.getLogger(__name__)


class SchemaBackend(Protocol):
    """Backend seam for live-schema inspection used by the verification flow.

    The verification flow -- diff each model's expected shape against the live
    table and report semantic Schema Drift under the active Schema Policy --
    lives in this module. Backends answer only with the shape a model expects
    and the shape a live table actually has; the shared flow diffs the two and
    names each divergence. Backends also identify known inspection limits.
    No backend creates schema: migrations do.
    """

    def verification_transaction(self) -> AbstractAsyncContextManager[None]: ...

    def expected_shape(self, planned_model: PlannedModel) -> TableShape: ...

    def verification_limits(
        self, planned_model: PlannedModel, /
    ) -> tuple[SchemaVerificationFact, ...]: ...

    async def inspect_shapes(
        self,
        planned_models: Sequence[PlannedModel],
    ) -> dict[str, TableShape]: ...


def validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    """Reject duplicate resolved table names before schema verification."""

    _ = build_schema_plan(models)


def validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    """Reject unsupported schema policy values."""

    validate_planned_schema_policy(schema_policy)


def _schema_drift_messages(
    verification_result: SchemaVerificationResult,
) -> tuple[str, ...]:
    """Group machine-readable issues into stable human diagnostics by table."""

    messages: list[str] = []
    for table_name in verification_result.checked_tables:
        details = tuple(
            issue.detail
            for issue in verification_result.issues
            if issue.table_name == table_name
        )
        if details:
            messages.append(
                f"schema drift detected for table {table_name!r}: {'; '.join(details)}"
            )
    return tuple(messages)


def _report_schema_drift(
    schema_policy: SchemaPolicy,
    verification_result: SchemaVerificationResult,
) -> None:
    messages = _schema_drift_messages(verification_result)
    if not messages:
        return
    if schema_policy == "strict":
        raise SchemaVerificationError(
            " | ".join(messages),
            result=verification_result,
        )
    for message in messages:
        logger.warning("%s", message)


def _verify_model_schema(
    backend: SchemaBackend,
    planned_model: PlannedModel,
    actual_shape: TableShape,
) -> tuple[tuple[str, ...], tuple[SchemaVerificationFact, ...]]:
    """Collect evidence without allowing a scope limit to suppress existing drift."""
    expected_shape = backend.expected_shape(planned_model)
    issues, facts = compare_table_shapes(expected_shape, actual_shape)
    compared = {(fact.kind, fact.object_name) for fact in facts}
    facts += tuple(
        fact
        for fact in backend.verification_limits(planned_model)
        if (fact.kind, fact.object_name) not in compared
    )
    if not issues:
        logger.debug(
            "schema table and indexes for %r verified", planned_model.table_name
        )
    return issues, facts


async def verify_schema(
    backend: SchemaBackend,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> SchemaVerificationResult:
    """Verify all configured tables against the live schema through one backend.

    Migrations are the sole schema-creation authority (ADR 0007): a missing
    table is reported as Schema Drift, never created, so the models stay the
    enforced contract the migration chain must converge to.
    """

    validate_schema_policy(schema_policy)
    plan = build_schema_plan(models)
    if not plan.models:
        return SchemaVerificationResult(checked_tables=(), issues=())
    logger.debug("schema verification started for %d model(s)", len(plan.models))
    drift_issues: list[SchemaDriftIssue] = []
    facts: list[SchemaVerificationFact] = []
    async with backend.verification_transaction():
        actual_shapes = await backend.inspect_shapes(plan.models)
        for planned_model in plan.models:
            actual_shape = actual_shapes.get(planned_model.table_name)
            if actual_shape is None:
                missing_issue = "table is missing from the database"
                facts.append(
                    SchemaVerificationFact(
                        table_name=planned_model.table_name,
                        object_name=None,
                        kind="table.presence",
                        status="drift",
                        detail=missing_issue,
                    )
                )
                drift_issues.append(
                    SchemaDriftIssue(
                        detail=missing_issue,
                        table_name=planned_model.table_name,
                    )
                )
                continue
            issues, table_facts = _verify_model_schema(
                backend, planned_model, actual_shape
            )
            facts.extend(table_facts)
            drift_issues.extend(
                SchemaDriftIssue(
                    detail=detail,
                    table_name=planned_model.table_name,
                )
                for detail in issues
            )
    verification_result = SchemaVerificationResult(
        checked_tables=tuple(model.table_name for model in plan.models),
        issues=tuple(drift_issues),
        facts=tuple(facts),
    )
    _report_schema_drift(schema_policy, verification_result)
    logger.debug("schema verification completed for %d model(s)", len(plan.models))
    return verification_result
