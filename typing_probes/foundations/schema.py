"""One ordinary dataclass is the source for the generated facade experiment."""

from dataclasses import dataclass, field


@dataclass(kw_only=True)
class Account:
    """Read rows require an ID; insert may omit the database-generated ID."""

    age: int
    id: int = field(metadata={"generated": True})
    name: str
    nickname: str | None = None
