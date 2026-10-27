"""Repository-only MariaDB artifact ownership for benchmarks and test fixtures."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from anyio import CancelScope, TemporaryDirectory


@asynccontextmanager
async def mariadb_artifacts() -> AsyncIterator[Path]:
    """Remove successful work only after resource teardown; retain failure evidence.

    Enter before the server context so its children stop before filesystem cleanup.
    On error, retain the private root rather than deleting potentially live data;
    the exception note reports its location without disclosing log contents.
    """

    owner = TemporaryDirectory(prefix="sq-", delete=False)
    async with owner as directory:
        root = Path(directory)
        try:
            yield root
            with CancelScope(shield=True):
                await owner.cleanup()
        except BaseException as error:
            error.add_note(f"MariaDB artifacts may remain at {root}")
            raise
