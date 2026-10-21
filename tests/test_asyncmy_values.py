"""Public raw-query value contracts for the isolated asyncmy adapter."""

from json import loads

from anyio import run_process
from snektest import Param, assert_eq, assert_not_in, test


@test([Param("buffered", name="buffered"), Param("stream", name="stream")], mark="slow")
async def native_values_expose_shared_negative_duration_binding_mismatch(
    consumption: str,
) -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            f"values-{consumption}",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(observed["chunk_sizes"], [2, 2, 1] if consumption == "stream" else [])
        assert_eq(
            observed["types"][0],
            [
                "int",
                "bytes",
                "Decimal",
                "datetime",
                "date",
                "timedelta",
                "str",
                "int",
                "int",
                "float",
            ],
        )
        assert_eq(
            observed["rows"][0],
            [
                1,
                bytes(range(256)).hex(),
                "-12345678901234567890.123456789",
                "2024-02-29T23:59:58.123456",
                "2024-02-29",
                -172803456789,
                "雪 🐍 ' \" \\ \u0000",
                -9223372036854775808,
                18446744073709551615,
                1.25,
            ],
        )
        assert_eq(observed["rows"][1], [2, *([None] * 9)])
        assert_eq(
            observed["rows"][2],
            [3, "", "0E-9", None, None, None, "", None, None, None],
        )
        assert_eq(observed["duration_expected_us"], -172796543211)
        assert_eq(observed["duration_exact"], False)
        assert_eq(observed["stored_duration"], "-48:00:03.456789")
        assert_eq(
            observed["rows"][3],
            [4, None, None, None, None, -172796543211, None, None, None, None],
        )
        assert_eq(
            observed["rows"][4],
            [5, None, None, None, None, 172803456789, None, None, None, None],
        )
        assert_eq(observed["warnings"], [])


@test([Param("buffered", name="buffered"), Param("stream", name="stream")], mark="slow")
async def native_warning_text_is_not_forwarded_but_unrelated_warnings_survive(
    consumption: str,
) -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            f"warnings-{consumption}",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    assert_not_in(
        "probe-warning-secret-value", result.stdout.decode() + result.stderr.decode()
    )
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["value"],
                r["server_warning_present"],
                r["server_warning_codes"],
                r["warnings"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", 0, True, [1292], ["unrelated-probe-warning"]),
            ("asyncmy", 0, True, [1292], ["unrelated-probe-warning"]),
        ],
    )
