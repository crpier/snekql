"""Each caller contract gets a clean control and an isolated negative probe."""

from json import loads
from pathlib import Path

from anyio import Path as AsyncPath
from snektest import Param, assert_eq, test

from typing_probes.foundations.check import Case, check_case


@test(
    [
        Param(value="fetched-model-construction", name="fetched-model-construction"),
        Param(
            value="fetched-required-constructor", name="fetched-required-constructor"
        ),
        Param(value="fetched-select", name="fetched-select"),
        Param(value="fetched-insert", name="fetched-insert"),
        Param(value="fetched-insert-owner", name="fetched-insert-owner"),
        Param(value="fetched-update", name="fetched-update"),
        Param(value="fetched-delete", name="fetched-delete"),
        Param(value="fetched-comparison", name="fetched-comparison"),
        Param(
            value="fetched-missing-insert-field", name="fetched-missing-insert-field"
        ),
        Param(
            value="fetched-missing-update-assignment",
            name="fetched-missing-update-assignment",
        ),
        Param(value="incremental-pair-inference", name="incremental-pair-inference"),
        Param(
            value="projection-constructor-check", name="projection-constructor-check"
        ),
        Param(value="projection-ten-slots", name="projection-ten-slots"),
        Param(
            value="projection-constructor-arity", name="projection-constructor-arity"
        ),
        Param(value="aggregate-nullable-sum", name="aggregate-nullable-sum"),
        Param(value="aggregate-having", name="aggregate-having"),
        Param(
            value="aggregate-ungrouped-selection", name="aggregate-ungrouped-selection"
        ),
        Param(value="dataclass-select", name="dataclass-select"),
        Param(value="dataclass-insert", name="dataclass-insert"),
        Param(value="dataclass-required-insert", name="dataclass-required-insert"),
        Param(value="dataclass-generated-insert", name="dataclass-generated-insert"),
        Param(value="dataclass-nullable-value", name="dataclass-nullable-value"),
        Param(value="dataclass-update", name="dataclass-update"),
        Param(value="dataclass-delete", name="dataclass-delete"),
        Param(value="dataclass-aggregate", name="dataclass-aggregate"),
        Param(value="dataclass-computed-selector", name="dataclass-computed-selector"),
        Param(value="dataclass-constant-selector", name="dataclass-constant-selector"),
        Param(
            value="dataclass-same-row-table-scope",
            name="dataclass-same-row-table-scope",
        ),
        Param(value="generated-insert", name="generated-insert"),
        Param(value="generated-insert-value", name="generated-insert-value"),
        Param(value="generated-insert-keyword", name="generated-insert-keyword"),
        Param(value="generated-id-override", name="generated-id-override"),
        Param(value="generated-read-id-required", name="generated-read-id-required"),
        Param(value="generated-select", name="generated-select"),
        Param(value="generated-update", name="generated-update"),
        Param(value="generated-delete", name="generated-delete"),
        Param(value="generated-aggregate", name="generated-aggregate"),
        Param(
            value="projection-keyword-constructor",
            name="projection-keyword-constructor",
        ),
        Param(
            value="projection-keyword-constructor-direct",
            name="projection-keyword-constructor-direct",
        ),
        Param(
            value="projection-nullable-aggregate-constructor",
            name="projection-nullable-aggregate-constructor",
        ),
    ],
    mark="slow",
)
async def caller_contract(value: str) -> None:
    """Unexpected acceptance and unrelated diagnostic failures both fail the probe."""
    directory = AsyncPath(Path(__file__).parents[2]) / "typing_probes/foundations"
    definitions = loads(await (directory / "cases.json").read_text())
    case = next(
        Case(**definition) for definition in definitions if definition["name"] == value
    )

    observation = await check_case(case)

    assert_eq(observation["conforms"], True, msg=str(observation))
