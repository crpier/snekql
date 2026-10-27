"""Private, non-replacing original-plan storage for the Linux deployment recipe.

Use an existing caller-owned directory, with access controls and backups suited
for sensitive evidence. This does not authenticate plans or back up the ledger.
It is a reading-resource example, not a new snekql persistence API.
"""

import asyncio
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from snekql.experimental import migrations as m


def _save(path: Path, text: str) -> None:
    """Publish a flushed 0600 file atomically without replacing an earlier original."""
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        # Same-filesystem hard-link publication refuses an existing destination.
        path.hardlink_to(temporary)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


async def save_original(path: Path, original: m.Prepared) -> None:
    """Persist original evidence off-loop before apply; never replace an existing file."""
    await asyncio.to_thread(_save, path, original.dump())


async def load_original(path: Path) -> m.Prepared:
    """Read the saved original, retaining its integrity/interpretation checks."""
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    return m.Prepared.load(text)
