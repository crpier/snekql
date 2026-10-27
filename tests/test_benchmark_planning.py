"""Planning validates benchmark intent without certifying native database work."""

from dataclasses import replace

from snektest import Param, assert_eq, assert_in, assert_raises, test

from benchmarks.comparison_plan import ComparisonPlan


@test(mark="fast")
def plan_rejects_zero_operations() -> None:
    """An invalid request cannot become a runnable comparison plan."""
    with assert_raises(ValueError) as error:
        ComparisonPlan(backend="sqlite", operations=0)
    assert_in("--operations must be between 1 and 100000", str(error.exception))


@test(mark="fast")
def seed_budget_rejects_a_combination_of_individually_valid_sizes() -> None:
    """Legal rows and payload widths can still exceed the table's 64 MiB budget."""
    with assert_raises(ValueError) as error:
        ComparisonPlan(backend="sqlite", rows=8193, payload_bytes=8192)
    assert_in("seed payload budget", str(error.exception))


@test(mark="fast")
def insert_budget_rejects_an_oversized_single_statement() -> None:
    """A bulk statement cannot exceed 8 MiB even when its seed is tiny."""
    with assert_raises(ValueError) as error:
        ComparisonPlan(
            backend="sqlite",
            workload="bulk",
            rows=1,
            operations=1,
            warmup=0,
            batch_size=1025,
            payload_bytes=8192,
        )
    assert_in("INSERT payload budget", str(error.exception))


@test(
    [Param("operations", name="measured"), Param("warmup", name="warmup")], mark="fast"
)
def write_budget_bounds_the_larger_phase_including_row_overhead(phase: str) -> None:
    """Measured and warmup writes each include 64 bytes of allowance per row."""
    plan = ComparisonPlan(
        backend="mariadb",
        workload="bulk",
        rows=1,
        operations=1,
        warmup=0,
        batch_size=1024,
        payload_bytes=64,
    )
    with assert_raises(ValueError) as error:
        replace(plan, **{phase: 1025})
    assert_in("write payload budget including row allowance", str(error.exception))


@test(mark="fast")
def plan_reports_effective_configuration_without_running_work() -> None:
    """Configuration describes requested policy, not fabricated observed results."""
    plan = ComparisonPlan(backend="sqlite", operations=2, rows=3, trials=1, warmup=0)
    assert_eq(
        plan.configuration,
        {
            "operations": 2,
            "adapter_order": "balanced",
            "rows": 3,
            "trials": 1,
            "warmup": 0,
            "workers": 1,
            "pool_size": 1,
            "payload_bytes": 32,
            "telemetry": "off",
            "buffering": "fetch-all",
            "validation": "strict-pydantic",
            "transaction": "explicit-begin-commit",
            "query_construction": "per-operation",
            "sqlite": {
                "journal_mode": "WAL",
                "synchronous": "NORMAL",
                "foreign_keys": True,
                "busy_timeout_ms": 5000,
            },
        },
    )


@test(mark="fast")
def measurement_labels_describe_scope_without_fabricating_measurements() -> None:
    """Memory profile labels never pretend setup or warmup were measured."""
    plan = ComparisonPlan(backend="mariadb", profile="memory")
    assert_eq(
        plan.measurement,
        {
            "profile": "memory",
            "heartbeat_interval_seconds": 0.005,
            "latency_includes_correctness_checks": True,
            "setup_included": False,
            "warmup_included": False,
        },
    )


@test(
    [
        Param(field, name=field)
        for field in ("backend", "adapter", "workload", "profile", "order", "telemetry")
    ],
    mark="fast",
)
def plans_reject_unknown_execution_labels(field: str) -> None:
    """Pure callers get invalid-intent errors rather than a plausible mislabeled plan."""
    with assert_raises(ValueError) as error:
        replace(ComparisonPlan(backend="sqlite"), **{field: "unsupported"})
    assert_in(field, str(error.exception))


@test(mark="fast")
def boolean_operation_count_is_not_a_numeric_work_request() -> None:
    """A Boolean must not leak into report counts as though it were an integer."""
    with assert_raises(ValueError):
        ComparisonPlan(backend="sqlite", operations=True)


@test(
    [
        Param((field, value), name=f"{field}-{edge}")
        for field, lower, upper in (
            ("workers", 1, 128),
            ("pool_size", 1, 32),
            ("payload_bytes", 1, 8192),
            ("batch_size", 1, 10000),
            ("operations", 1, 100000),
            ("rows", 1, 1000000),
            ("trials", 1, 30),
            ("warmup", 0, 10000),
        )
        for edge, value in (("lower", lower), ("upper", upper))
    ],
    mark="fast",
)
def numeric_boundaries_are_inclusive(boundary: tuple[str, int]) -> None:
    """Documented endpoints remain legal without allocating the requested work."""
    field, value = boundary
    plan = replace(ComparisonPlan(backend="sqlite"), **{field: value})
    assert_eq(getattr(plan, field), value)


@test(mark="fast")
def exact_joint_budgets_remain_usable_plans() -> None:
    """The ceiling is inclusive, and warmup/measured phases are not added together."""
    seed = ComparisonPlan(backend="sqlite", rows=8192, payload_bytes=8192)
    insert = ComparisonPlan(
        backend="mariadb",
        workload="bulk",
        rows=1,
        operations=1,
        warmup=0,
        batch_size=1024,
        payload_bytes=8192,
    )
    write = ComparisonPlan(
        backend="mariadb",
        workload="bulk",
        rows=1,
        operations=1024,
        warmup=1024,
        batch_size=1024,
        payload_bytes=64,
    )
    assert_eq(seed.configuration["rows"], 8192)
    assert_eq(insert.configuration["batch_size"], 1024)
    assert_eq(write.configuration["warmup"], 1024)


@test(
    [
        Param(
            (
                "balanced",
                6,
                [
                    "raw",
                    "snekql",
                    "sqlalchemy",
                    "snekql",
                    "sqlalchemy",
                    "raw",
                    "sqlalchemy",
                    "raw",
                    "snekql",
                    "sqlalchemy",
                    "snekql",
                    "raw",
                    "snekql",
                    "raw",
                    "sqlalchemy",
                    "raw",
                    "sqlalchemy",
                    "snekql",
                ],
            ),
            name="balanced",
        ),
        Param(
            (
                "forward",
                6,
                [
                    "raw",
                    "snekql",
                    "sqlalchemy",
                    "snekql",
                    "sqlalchemy",
                    "raw",
                    "sqlalchemy",
                    "raw",
                    "snekql",
                ]
                * 2,
            ),
            name="forward",
        ),
        Param(
            (
                "reverse",
                3,
                [
                    "sqlalchemy",
                    "snekql",
                    "raw",
                    "snekql",
                    "raw",
                    "sqlalchemy",
                    "raw",
                    "sqlalchemy",
                    "snekql",
                ],
            ),
            name="reverse",
        ),
    ],
    mark="fast",
)
def schedule_preserves_direction_and_balanced_cycles(
    example: tuple[str, int, list[str]],
) -> None:
    """Order is an explicit request policy, not a timing-dependent sorting result."""
    order, trials, expected = example
    plan = ComparisonPlan(backend="sqlite", order=order, trials=trials)
    assert_eq([trial.adapter for trial in plan.schedule], expected)
    assert_eq([trial.position for trial in plan.schedule], [1, 2, 3] * trials)


@test(
    [Param(adapter, name=adapter) for adapter in ("raw", "snekql", "sqlalchemy")],
    mark="fast",
)
def single_adapter_schedule_keeps_one_position_per_round(adapter: str) -> None:
    """Selecting one adapter never inserts unrelated adapters into its plan."""
    plan = ComparisonPlan(backend="mariadb", adapter=adapter, trials=3)
    assert_eq(
        [(trial.round, trial.position, trial.adapter) for trial in plan.schedule],
        [(1, 1, adapter), (2, 1, adapter), (3, 1, adapter)],
    )


@test(
    [
        Param(workload, name=workload)
        for workload in ("point-read", "join", "stream", "bulk")
    ],
    mark="fast",
)
def configuration_labels_buffering_and_batching_by_workload(workload: str) -> None:
    """Only streaming buffers with fetch-many; stream and bulk record batch size."""
    config = ComparisonPlan(
        backend="sqlite", workload=workload, batch_size=7
    ).configuration
    assert_eq(
        config["buffering"], "fetch-many" if workload == "stream" else "fetch-all"
    )
    assert_eq(config.get("batch_size"), 7 if workload in ("stream", "bulk") else None)


@test(mark="fast")
def editing_a_report_view_cannot_change_the_planned_session_policy() -> None:
    """Caller formatting must not mutate policy later used by native verification."""
    plan = ComparisonPlan(backend="mariadb")
    policy = plan.configuration["mariadb"]
    assert isinstance(policy, dict)
    policy["unique_checks"] = 0
    fresh = plan.configuration["mariadb"]
    assert isinstance(fresh, dict)
    assert_eq(fresh["unique_checks"], 1)
    assert_eq(fresh["time_zone"], "+00:00")


@test(
    [
        Param(("workers", 129), name="workers"),
        Param(("pool_size", 33), name="pool-size"),
        Param(("payload_bytes", 8193), name="payload-bytes"),
        Param(("batch_size", 10001), name="batch-size"),
        Param(("operations", 100001), name="operations"),
        Param(("rows", 1000001), name="rows"),
        Param(("trials", 31), name="trials"),
        Param(("warmup", 10001), name="warmup"),
    ],
    mark="fast",
)
def exceeding_any_numeric_ceiling_is_rejected(boundary: tuple[str, int]) -> None:
    """Each individual ceiling matters independently of joint payload budgets."""
    field, value = boundary
    with assert_raises(ValueError) as error:
        replace(ComparisonPlan(backend="sqlite"), **{field: value})
    assert_in(field.replace("_", "-"), str(error.exception))
