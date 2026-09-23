"""Check isolated caller contracts, including explicitly recorded limitations."""

from json import loads
from pathlib import Path

from anyio import Path as AsyncPath
from snektest import Param, assert_eq, test

from typing_probes.model_definitions.check import Case, check_case


@test(
    [
        Param(value="refined-required", name="refined-required"),
        Param(value="refined-value", name="refined-value"),
        Param(value="refined-keyword", name="refined-keyword"),
        Param(value="refined-explicit-id", name="refined-explicit-id"),
        Param(value="refined-id-not-null", name="refined-id-not-null"),
        Param(value="refined-nullable", name="refined-nullable"),
        Param(value="refined-pending-id", name="refined-pending-id"),
        Param(value="refined-read-id", name="refined-read-id"),
        Param(value="refined-read-created", name="refined-read-created"),
        Param(value="refined-server-override", name="refined-server-override"),
        Param(
            value="refined-read-rejects-omitted", name="refined-read-rejects-omitted"
        ),
        Param(value="refined-default", name="refined-default"),
        Param(value="refined-inherited-owner", name="refined-inherited-owner"),
        Param(value="refined-column-value", name="refined-column-value"),
        Param(value="refined-frozen", name="refined-frozen"),
        Param(value="refined-read-frozen", name="refined-read-frozen"),
        Param(value="refined-query-result", name="refined-query-result"),
        Param(value="refined-inherited-create", name="refined-inherited-create"),
        Param(value="borrowed-required", name="borrowed-required"),
        Param(value="borrowed-classmethod", name="borrowed-classmethod"),
        Param(value="borrowed-value", name="borrowed-value"),
        Param(value="borrowed-keyword", name="borrowed-keyword"),
        Param(value="borrowed-override", name="borrowed-override"),
        Param(value="borrowed-result", name="borrowed-result"),
        Param(
            value="borrowed-direct-construction-gap",
            name="borrowed-direct-construction-gap",
        ),
        Param(value="command-NewCommand-missing", name="command-NewCommand-missing"),
        Param(value="command-NewCommand-value", name="command-NewCommand-value"),
        Param(value="command-NewCommand-keyword", name="command-NewCommand-keyword"),
        Param(value="command-MetaCommand-missing", name="command-MetaCommand-missing"),
        Param(value="command-MetaCommand-value", name="command-MetaCommand-value"),
        Param(value="command-MetaCommand-keyword", name="command-MetaCommand-keyword"),
        Param(value="baseline-required", name="baseline-required"),
        Param(
            value="baseline-explicit-fetched-gap", name="baseline-explicit-fetched-gap"
        ),
        Param(value="baseline-default-mismatch", name="baseline-default-mismatch"),
        Param(value="implicit-generated-default", name="implicit-generated-default"),
        Param(
            value="unannotated-descriptor-constructor",
            name="unannotated-descriptor-constructor",
        ),
        Param(value="plain-annotated-column", name="plain-annotated-column"),
        Param(value="self-specialization", name="self-specialization"),
        Param(value="higher-kinded-model", name="higher-kinded-model"),
        Param(value="generic-typed-dict-unpack", name="generic-typed-dict-unpack"),
        Param(value="recursive-__new__", name="recursive-__new__"),
        Param(value="recursive-__call__", name="recursive-__call__"),
        Param(value="value-default-read", name="value-default-read"),
        Param(value="value-input-shape", name="value-input-shape"),
        Param(value="value-insert-shape", name="value-insert-shape"),
        Param(value="value-select", name="value-select"),
        Param(value="value-explicit-id", name="value-explicit-id"),
        Param(value="value-second-generated", name="value-second-generated"),
        Param(
            value="value-column-without-missing", name="value-column-without-missing"
        ),
        Param(value="value-direct-fetched-gap", name="value-direct-fetched-gap"),
        Param(value="decorator-required", name="decorator-required"),
        Param(value="decorator-value", name="decorator-value"),
        Param(value="decorator-not-a-type", name="decorator-not-a-type"),
        Param(value="decorator-column-namespace", name="decorator-column-namespace"),
        Param(
            value="refined-required-subclass-gap", name="refined-required-subclass-gap"
        ),
        Param(
            value="refined-required-subclass-repair",
            name="refined-required-subclass-repair",
        ),
        Param(
            value="refined-required-subclass-columns",
            name="refined-required-subclass-columns",
        ),
        Param(value="excluded-required", name="excluded-required"),
        Param(value="excluded-value", name="excluded-value"),
        Param(
            value="excluded-override-through-assignment",
            name="excluded-override-through-assignment",
        ),
        Param(value="excluded-override-owner", name="excluded-override-owner"),
        Param(value="excluded-no-id-keyword", name="excluded-no-id-keyword"),
        Param(
            value="excluded-direct-construction-gap",
            name="excluded-direct-construction-gap",
        ),
        Param(value="client-generated-key", name="client-generated-key"),
        Param(
            value="readonly-typed-dict-refinement",
            name="readonly-typed-dict-refinement",
        ),
        Param(value="readonly-typed-dict-columns", name="readonly-typed-dict-columns"),
        Param(value="baseline-inherited-witness", name="baseline-inherited-witness"),
        Param(value="runtime_refined-required", name="runtime_refined-required"),
        Param(value="runtime_refined-value", name="runtime_refined-value"),
        Param(value="runtime_refined-keyword", name="runtime_refined-keyword"),
        Param(value="runtime_refined-override", name="runtime_refined-override"),
        Param(value="runtime_refined-null-id", name="runtime_refined-null-id"),
        Param(value="runtime_refined-nullable", name="runtime_refined-nullable"),
        Param(
            value="runtime_refined-second-generated",
            name="runtime_refined-second-generated",
        ),
        Param(value="runtime_refined-frozen", name="runtime_refined-frozen"),
        Param(value="runtime_refined-read-id", name="runtime_refined-read-id"),
        Param(value="runtime_single-required", name="runtime_single-required"),
        Param(value="runtime_single-value", name="runtime_single-value"),
        Param(value="runtime_single-keyword", name="runtime_single-keyword"),
        Param(value="runtime_single-override", name="runtime_single-override"),
        Param(value="runtime_single-null-id", name="runtime_single-null-id"),
        Param(value="runtime_single-nullable", name="runtime_single-nullable"),
        Param(
            value="runtime_single-second-generated",
            name="runtime_single-second-generated",
        ),
        Param(value="runtime_single-frozen", name="runtime_single-frozen"),
        Param(value="runtime_single-read-id", name="runtime_single-read-id"),
        Param(
            value="runtime-refined-required-read", name="runtime-refined-required-read"
        ),
        Param(
            value="runtime-refined-input-marker", name="runtime-refined-input-marker"
        ),
        Param(value="runtime-refined-owner", name="runtime-refined-owner"),
        Param(
            value="runtime-refined-bad-override-gap",
            name="runtime-refined-bad-override-gap",
        ),
        Param(value="runtime-single-direct-gap", name="runtime-single-direct-gap"),
        Param(
            value="runtime-single-explicit-omit-rejected",
            name="runtime-single-explicit-omit-rejected",
        ),
        Param(
            value="value-parameter-inference-escape",
            name="value-parameter-inference-escape",
        ),
        Param(
            value="bounded-value-inference-repair",
            name="bounded-value-inference-repair",
        ),
        Param(value="bounded-value-null-rejected", name="bounded-value-null-rejected"),
        Param(value="bounded-value-pending", name="bounded-value-pending"),
        Param(value="foreign-required", name="foreign-required"),
        Param(value="foreign-value", name="foreign-value"),
        Param(
            value="foreign-target-declaration-gap",
            name="foreign-target-declaration-gap",
        ),
        Param(value="runtime-default-mismatch", name="runtime-default-mismatch"),
        Param(
            value="runtime-default-factory-mismatch",
            name="runtime-default-factory-mismatch",
        ),
        Param(
            value="foreign-target-erased-control", name="foreign-target-erased-control"
        ),
        Param(value="foreign-reference-operation", name="foreign-reference-operation"),
        Param(
            value="foreign-descriptor-assignment", name="foreign-descriptor-assignment"
        ),
        Param(value="method-declared-field", name="method-declared-field"),
        Param(
            value="baseline-foreign-declaration-gap",
            name="baseline-foreign-declaration-gap",
        ),
        Param(
            value="input-generic-base-alternative",
            name="input-generic-base-alternative",
        ),
        Param(
            value="runtime-generated-explicit-marker",
            name="runtime-generated-explicit-marker",
        ),
        Param(
            value="runtime-generated-column-domain",
            name="runtime-generated-column-domain",
        ),
        Param(
            value="baseline-immutability-not-static",
            name="baseline-immutability-not-static",
        ),
        Param(
            value="frozen-existing-immutability", name="frozen-existing-immutability"
        ),
        Param(value="frozen-existing-constructor", name="frozen-existing-constructor"),
        Param(
            value="frozen-existing-column-update", name="frozen-existing-column-update"
        ),
    ],
    mark="slow",
)
async def model_typing_observation(value: str) -> None:
    """A matching observation is not necessarily a successful static rejection."""
    directory = AsyncPath(Path(__file__).parents[2]) / "typing_probes/model_definitions"
    definitions = loads(await (directory / "cases.json").read_text())
    case = next(
        Case(**definition) for definition in definitions if definition["name"] == value
    )

    observation = await check_case(case)

    assert_eq(observation["conforms"], True, msg=str(observation))
