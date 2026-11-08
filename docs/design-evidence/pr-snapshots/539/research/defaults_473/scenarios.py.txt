"""Scenario-first visual comparison for #473. Read this file; do not run examples.

Each function is one scenario; its three declarations are ALTERNATIVES for the
same model field, not three fields to put in one model. Model/Row boilerplate is
omitted so the declaration differences stay visible.

    db        = current SQLite API (also representative of MariaDB here)
    separate  = proposed default / server_default API, NOT an installed module
    selector  = proposed default_on API, NOT an installed module

The proposed namespaces are placeholders, not implementations. no_type_check
allows this visual document to contain hypothetical APIs and deliberate errors.
It is NOT typing evidence: tests extract the eleven core declarations and check
those against the existing native research signatures and consumer controls.
These are the earlier split signatures; callable-intersections.md documents a
newer no-pending-boilerplate variant with an explicit required-input override.
Nothing here executes a model, factory, constructor or SQL. TYPE_CHECKING keeps
all examples inactive. Initial values and SQL comments describe existing or
intended semantics, not newly executed runtime proof. No design is selected.
"""

# Visual alternatives intentionally leave locals unused and show commented variants.
# ruff: noqa: ERA001, F841, FBT003

from typing import TYPE_CHECKING, Any, no_type_check

if TYPE_CHECKING:
    from uuid import UUID, uuid4

    from snekql import sqlite as db

    separate: Any
    selector: Any

    # =====================================================================
    # COMMON SCENARIOS: current, separate parameters, selector — in that order
    # =====================================================================

    @no_type_check
    def scenario_01_required_non_nullable() -> None:
        """Omission rejected; str accepted; None rejected. SQL: NOT NULL, no default.

        Pending: str. Row: str. INSERT supplies the caller's value.
        """
        # Approach 1 — current
        value: db.Col[str] = db.Text()

        # Approach 2 — separate parameters
        value: db.Col[str] = separate.Text()

        # Approach 3 — selector
        value: db.Col[str] = selector.Text()

    @no_type_check
    def scenario_02_required_nullable() -> None:
        """Omission rejected; str OR None accepted. SQL: nullable, no default.

        Pending: str | None. Row: str | None. INSERT supplies value or NULL.
        Being nullable does not make the constructor argument optional.
        """
        # Approach 1 — current
        value: db.Col[str | None] = db.Text()

        # Approach 2 — separate parameters
        value: db.Col[str | None] = separate.Text()

        # Approach 3 — selector
        value: db.Col[str | None] = selector.Text()

    @no_type_check
    def scenario_03_python_value_default() -> None:
        """Omission gives 7; int overrides; None rejected. SQL: NOT NULL, no default.

        Pending: int. Row: int. INSERT supplies the Python value, including 7.
        """
        # Approach 1 — current
        value: db.Col[int] = db.Integer(default=7)

        # Approach 2 — separate parameters
        value: db.Col[int] = separate.Integer(default=7)

        # Approach 3 — selector (Python ownership is the default mode)
        value: db.Col[int] = selector.Integer(default=7)
        # Explicit equivalent: selector.Integer(default=7, default_on="python")

    @no_type_check
    def scenario_04_python_none_default() -> None:
        """Omission gives None; str OR None accepted. SQL: nullable, no default.

        Pending: str | None. Row: str | None. Omitted input sends NULL in INSERT.
        """
        # Approach 1 — current
        value: db.Col[str | None] = db.Text(default=None)

        # Approach 2 — separate parameters
        value: db.Col[str | None] = separate.Text(default=None)

        # Approach 3 — selector
        value: db.Col[str | None] = selector.Text(default=None)

    @no_type_check
    def scenario_05_nullable_python_value_default() -> None:
        """Omission gives guest; str OR None accepted. SQL: nullable, no default.

        Pending: str | None. Row: str | None. INSERT supplies value or NULL.
        Compare scenario 04: same types, different value on omission.
        """
        # Approach 1 — current
        value: db.Col[str | None] = db.Text(default="guest")

        # Approach 2 — separate parameters
        value: db.Col[str | None] = separate.Text(default="guest")

        # Approach 3 — selector
        value: db.Col[str | None] = selector.Text(default="guest")

    @no_type_check
    def scenario_06_python_factory() -> None:
        """Omission gives a factory-produced UUID; UUID overrides; None rejected.

        Pending: UUID. Row: UUID. SQL: NOT NULL, no default. INSERT supplies UUID.
        Pass uuid4, not uuid4(): this file never calls the factory.
        """
        # Approach 1 — current
        value: db.Col[UUID] = db.Text(default_factory=uuid4)

        # Approach 2 — separate parameters
        value: db.Col[UUID] = separate.Text(default_factory=uuid4)

        # Approach 3 — selector
        value: db.Col[UUID] = selector.Text(default_factory=uuid4)

    @no_type_check
    def scenario_07_server_literal_default() -> None:
        """Omission gives PENDING_GENERATION, NOT False; bool overrides; no None.

        Pending: bool | PENDING_GENERATION. Row: bool. SQL: NOT NULL, DEFAULT 0.
        INSERT omits pending; an explicit bool is supplied instead.
        """
        # Approach 1 — current
        value: db.GenCol[bool] = db.Integer(default=db.LiteralDefault(False))

        # Approach 2 — separate parameters
        value: db.GenCol[bool] = separate.Integer(
            default=db.PENDING_GENERATION,
            server_default=False,
        )

        # Approach 3 — selector
        value: db.GenCol[bool] = selector.Integer(default=False, default_on="server")

    @no_type_check
    def scenario_08_server_expression_default() -> None:
        """Omission gives PENDING_GENERATION, NOT a Python timestamp; no None.

        Explicit UtcDatetime overrides. Pending: UtcDatetime | PENDING_GENERATION.
        Row: UtcDatetime. SQL: NOT NULL, backend UTC-clock default.
        INSERT omits pending; an explicit timestamp is supplied instead.
        """
        # Approach 1 — current
        value: db.GenCol[db.UtcDatetime] = db.Text(default=db.CurrentTimestamp)

        # Approach 2 — separate parameters
        value: db.GenCol[db.UtcDatetime] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default=db.CurrentTimestamp,
        )

        # Approach 3 — selector
        value: db.GenCol[db.UtcDatetime] = selector.Text(
            default=db.CurrentTimestamp,
            default_on="server",
        )

    @no_type_check
    def scenario_09_nullable_server_default() -> None:
        """Omission gives PENDING_GENERATION; str overrides; None sends SQL NULL.

        Pending: str | None | PENDING_GENERATION. Row: str | None.
        SQL: nullable, DEFAULT 'fallback'. INSERT omits pending, supplies value/NULL.
        An explicit None does NOT ask for fallback.
        """
        # Approach 1 — current
        value: db.GenCol[str | None] = db.Text(default=db.LiteralDefault("fallback"))

        # Approach 2 — separate parameters
        value: db.GenCol[str | None] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default="fallback",
        )

        # Approach 3 — selector
        value: db.GenCol[str | None] = selector.Text(
            default="fallback",
            default_on="server",
        )

    @no_type_check
    def scenario_10_server_null_default() -> None:
        """Omission gives PENDING_GENERATION, NOT None; str OR None accepted.

        Pending: str | None | PENDING_GENERATION. Row: str | None.
        SQL: nullable, DEFAULT NULL. INSERT omits pending, supplies value/NULL.
        Omission and explicit None remain distinct even if both result in SQL NULL.
        """
        # Approach 1 — current
        value: db.GenCol[str | None] = db.Text(default=db.LiteralDefault(None))

        # Approach 2 — separate parameters
        value: db.GenCol[str | None] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default=None,
        )

        # Approach 3 — selector
        value: db.GenCol[str | None] = selector.Text(default=None, default_on="server")

    @no_type_check
    def scenario_11_identity() -> None:
        """Omission gives PENDING_GENERATION; int overrides where supported; no None.

        Pending: int | PENDING_GENERATION. Row: int. INSERT omits pending.
        SQL: primary key / identity / auto-increment, NOT a SQL DEFAULT.
        The selector does not replace pending for this identity declaration.
        """
        # Approach 1 — current
        value: db.GenCol[int] = db.Integer(
            default=db.PENDING_GENERATION,
            primary_key=True,
            auto_increment=True,
        )

        # Approach 2 — separate parameters
        value: db.GenCol[int] = separate.Integer(
            default=db.PENDING_GENERATION,
            primary_key=True,
            auto_increment=True,
        )

        # Approach 3 — selector
        value: db.GenCol[int] = selector.Integer(
            default=db.PENDING_GENERATION,
            primary_key=True,
            auto_increment=True,
        )

    # =====================================================================
    # ADDITIONAL AGREED COMPARISONS — not requirements that a design must meet
    # =====================================================================

    @no_type_check
    def extra_nullable_server_clock() -> None:
        """Omission uses server clock; an explicit None can mean never expires.

        Pending: UtcDatetime | None | PENDING_GENERATION. Row: UtcDatetime | None.
        SQL: nullable, UTC-clock default. INSERT omits pending, supplies value/NULL.
        """
        # Approach 1 — current
        value: db.GenCol[db.UtcDatetime | None] = db.Text(default=db.CurrentTimestamp)

        # Approach 2 — separate parameters
        value: db.GenCol[db.UtcDatetime | None] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default=db.CurrentTimestamp,
        )

        # Approach 3 — selector
        value: db.GenCol[db.UtcDatetime | None] = selector.Text(
            default=db.CurrentTimestamp,
            default_on="server",
        )

    @no_type_check
    def contrast_01_required_python_input_with_server_default() -> None:
        """Input required; bool accepted, no None; SQL default is for other writers.

        Pending: bool. Row: bool. SQL: NOT NULL, DEFAULT 0.
        This caller always supplies a value; other writers can use the SQL default.
        """
        # Approach 1 — current
        # No equivalent public default form: a server marker also permits omission.

        # Approach 2 — separate parameters
        value: db.Col[bool] = separate.Integer(server_default=False)

        # Approach 3 — selector
        # No equivalent in the tested prototype; not impossible in the design family.

    @no_type_check
    def contrast_02_python_default_and_server_default_together() -> None:
        """Python initial False, SQL fallback True. INSERT supplies Python's value.

        Pending: bool. Row: bool. SQL: NOT NULL, DEFAULT 1.
        SQL fallback is for other writers, not this constructor's omitted input.
        """
        # Approach 1 — current
        # No equivalent public form with independently specified defaults.

        # Approach 2 — separate parameters
        value: db.Col[bool] = separate.Integer(default=False, server_default=True)
        # Factory variant: separate.Text(
        #     default_factory=lambda: "client", server_default="server"
        # ) on Col[str]: Python result "client", SQL fallback "server".

        # Approach 3 — selector
        # No equivalent in the tested prototype; not impossible in the design family.

    @no_type_check
    def contrast_03_required_generated_input() -> None:
        """GenCol does NOT itself promise omission or a declared generation source.

        All three: Entry() rejected; Entry(value="given") accepted;
        Entry(value=db.PENDING_GENERATION) accepted. Do not execute these calls.
        Pending: str | PENDING_GENERATION. Row: str. No SQL default is declared.
        """
        # Approach 1 — current
        value: db.GenCol[str] = db.Text()

        # Approach 2 — separate parameters
        value: db.GenCol[str] = separate.Text()

        # Approach 3 — selector
        value: db.GenCol[str] = selector.Text()

    # =====================================================================
    # POSSIBLE INVALID CASES / NEAR-MISSES
    #
    # "Rejected" below means the existing native-ty probes reject the form,
    # NOT that this deliberately unchecked visual document emits diagnostics.
    # "Accepted gap" means static acceptance, NOT proven runtime acceptance.
    # =====================================================================

    @no_type_check
    def invalid_01_wrong_python_value_type() -> None:
        """Rejected in all three: bool default on a str field."""
        # Approach 1 — current
        value: db.Col[str] = db.Integer(default=False)

        # Approach 2 — separate parameters
        value: db.Col[str] = separate.Integer(default=False)

        # Approach 3 — selector
        value: db.Col[str] = selector.Integer(default=False)

    @no_type_check
    def invalid_02_python_none_on_non_nullable_field() -> None:
        """Rejected in all three: None default without None in the logical type."""
        # Approach 1 — current
        value: db.Col[str] = db.Text(default=None)

        # Approach 2 — separate parameters
        value: db.Col[str] = separate.Text(default=None)

        # Approach 3 — selector
        value: db.Col[str] = selector.Text(default=None)

    @no_type_check
    def invalid_03_wrong_factory_result() -> None:
        """Rejected in all three: UUID factory for a str field."""
        # Approach 1 — current
        value: db.Col[str] = db.Text(default_factory=uuid4)

        # Approach 2 — separate parameters
        value: db.Col[str] = separate.Text(default_factory=uuid4)

        # Approach 3 — selector
        value: db.Col[str] = selector.Text(default_factory=uuid4)

    def needs_argument(seed: int) -> UUID:
        """Only a callback signature example; never called."""
        return UUID(int=seed)

    @no_type_check
    def invalid_04_factory_requires_an_argument() -> None:
        """Rejected in all three: a default factory must be callable with no args."""
        # Approach 1 — current
        value: db.Col[UUID] = db.Text(default_factory=needs_argument)

        # Approach 2 — separate parameters
        value: db.Col[UUID] = separate.Text(default_factory=needs_argument)

        # Approach 3 — selector
        value: db.Col[UUID] = selector.Text(default_factory=needs_argument)

    @no_type_check
    def invalid_05_wrong_server_literal_type() -> None:
        """Rejected in all three: bool SQL default on a str field."""
        # Approach 1 — current
        value: db.GenCol[str] = db.Integer(default=db.LiteralDefault(False))

        # Approach 2 — separate parameters
        value: db.GenCol[str] = separate.Integer(
            default=db.PENDING_GENERATION,
            server_default=False,
        )

        # Approach 3 — selector
        value: db.GenCol[str] = selector.Integer(default=False, default_on="server")

    @no_type_check
    def invalid_06_server_null_on_non_nullable_field() -> None:
        """Rejected in all three: SQL NULL default without nullable logical type."""
        # Approach 1 — current
        value: db.GenCol[str] = db.Text(default=db.LiteralDefault(None))

        # Approach 2 — separate parameters
        value: db.GenCol[str] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default=None,
        )

        # Approach 3 — selector
        value: db.GenCol[str] = selector.Text(default=None, default_on="server")

    @no_type_check
    def invalid_07_server_omission_on_plain_col() -> None:
        """Rejected in all three: pending initial state needs GenCol, not plain Col."""
        # Approach 1 — current
        value: db.Col[bool] = db.Integer(default=db.LiteralDefault(False))

        # Approach 2 — separate parameters
        value: db.Col[bool] = separate.Integer(
            default=db.PENDING_GENERATION,
            server_default=False,
        )

        # Approach 3 — selector
        value: db.Col[bool] = selector.Integer(default=False, default_on="server")

    @no_type_check
    def invalid_08_clock_on_wrong_logical_type() -> None:
        """Incoherent SQL clock -> str. Current accepts statically; others reject.

        Current production source has a UTC-type runtime guard, NOT executed here.
        GenCol[None] is another accepted current gap / rejected prototype form.
        Stricter typing need not require changing the public syntax.
        """
        # Approach 1 — current: ACCEPTED GAP in ty
        value: db.GenCol[str] = db.Text(default=db.CurrentTimestamp)

        # Approach 2 — separate parameters: REJECTED in this omission form
        value: db.GenCol[str] = separate.Text(
            default=db.PENDING_GENERATION,
            server_default=db.CurrentTimestamp,
        )

        # Approach 3 — selector: REJECTED
        value: db.GenCol[str] = selector.Text(
            default=db.CurrentTimestamp,
            default_on="server",
        )

    @no_type_check
    def invalid_09_value_and_factory_at_the_same_time() -> None:
        """Rejected in all three: two competing Python-default mechanisms."""
        # Approach 1 — current
        value: db.Col[str] = db.Text(default="value", default_factory=lambda: "value")

        # Approach 2 — separate parameters
        value: db.Col[str] = separate.Text(
            default="value", default_factory=lambda: "value"
        )

        # Approach 3 — selector
        value: db.Col[str] = selector.Text(
            default="value", default_factory=lambda: "value"
        )

    @no_type_check
    def invalid_10_required_input_with_bad_sql_default() -> None:
        """Separate's C1 typing gap: constructor precision does not validate SQL.

        These separate-parameter declarations are accepted by tested ty signatures
        despite incompatible SQL defaults. Runtime declaration validation needed.
        """
        # Approach 1 — current
        # No corresponding required-input + SQL-default form.

        # Approach 2 — separate parameters: ACCEPTED GAPS
        wrong_literal: db.Col[int] = separate.Integer(server_default="wrong")
        wrong_null: db.Col[str] = separate.Text(server_default=None)
        wrong_clock: db.Col[str] = separate.Text(server_default=db.CurrentTimestamp)

        # Approach 3 — selector
        # No corresponding form in the tested prototype.

    @no_type_check
    def invalid_11_selector_specific_mistakes() -> None:
        """All three selector calls below are rejected by the tested signatures."""
        # Approach 1 — current: no selector parameter.
        # Approach 2 — separate parameters: no selector parameter.

        # Approach 3 — selector
        # Invalid owner string (the tested names are "python" and "server").
        wrong_owner: db.GenCol[bool] = selector.Integer(
            default=False, default_on="elsewhere"
        )
        # Owner without a default value.
        missing_value: db.GenCol[bool] = selector.Integer(default_on="server")
        # A Python callable is not a server-side SQL factory.
        server_factory: db.GenCol[UUID] = selector.Text(
            default_factory=uuid4, default_on="server"
        )

    @no_type_check
    def risky_12_generation_requested_without_a_declared_source() -> None:
        """Accepted route in all three; generation is NOT certified to succeed.

        Required input, no SQL generation source declared. Explicitly constructing
        Entry(value=db.PENDING_GENERATION) is still statically accepted. Without an
        external source this can fail at INSERT. Omission is rejected in all three.
        """
        # Approach 1 — current
        value: db.GenCol[int] = db.Integer()
        # Current also permits omission with this source-less declaration:
        # value: db.GenCol[int] = db.Integer(default=db.PENDING_GENERATION)

        # Approach 2 — separate parameters
        value: db.GenCol[int] = separate.Integer()

        # Approach 3 — selector
        value: db.GenCol[int] = selector.Integer()

    @no_type_check
    def surprising_13_plain_false_still_does_not_declare_an_sql_default() -> None:
        """VALID in all three, but preserves the original #473 misunderstanding.

        Omission gives Python False, INSERT supplies False, SQL has NO DEFAULT.
        Pairing any of these with hand-written DEFAULT 0 still describes different
        schemas. None of the proposed interfaces makes this mistake impossible.
        """
        # Approach 1 — current
        value: db.Col[bool] = db.Integer(default=False)

        # Approach 2 — separate parameters
        value: db.Col[bool] = separate.Integer(default=False)

        # Approach 3 — selector (implicit Python mode)
        value: db.Col[bool] = selector.Integer(default=False)
