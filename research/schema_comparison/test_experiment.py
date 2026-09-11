"""Contract tests for the standalone research runner."""

from snektest import Param, assert_eq, assert_in, test

from research.schema_comparison.experiment import sqlite_observation
from research.schema_comparison.sqlalchemy_models import ddl


@test(mark="medium")
async def duplicate_email_is_rejected() -> None:
    """Raw SQL must exercise the installed unique constraint."""
    observation = await sqlite_observation("snekql", "matched")
    assert_eq(observation["probes"]["duplicate_email"]["outcome"], "rejected")


@test(mark="medium")
async def profile_delete_cascades() -> None:
    """Deleting an unreferenced user removes their profile in the database."""
    observation = await sqlite_observation("snekql", "matched")
    assert_eq(observation["probes"]["profile_cascade"]["rows"], [[0]])


@test(mark="fast")
def matched_mariadb_uses_64_bit_ids() -> None:
    """Matched intent must include the integer range, not just small seed IDs."""
    assert_in("BIGINT", ddl("mariadb", "matched")[0])


@test(
    [Param(value=library, name=library) for library in ("snekql", "sqlalchemy")],
    [Param(value=track, name=track) for track in ("idiomatic", "matched")],
    mark="medium",
)
async def common_contract_has_no_mismatches(library: str, track: str) -> None:
    """The runner evaluates each independent SQL specification without mismatches."""
    observation = await sqlite_observation(library, track)
    assert_eq(
        [
            name
            for name, probe in observation["probes"].items()
            if probe["matches_spec"] is False
        ],
        [],
    )
