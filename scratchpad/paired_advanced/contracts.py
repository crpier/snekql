"""Application results are independent of either storage declaration layout."""

from typing import NewType

from pydantic import BaseModel

UserId = NewType("UserId", int)
PostId = NewType("PostId", int)


class AccountSummary(BaseModel):
    balance: int
    email: str


class BalanceGroup(BaseModel):
    balance: int
    total: int


class ReferralStep(BaseModel):
    depth: int
    inviter_id: UserId | None
    user_id: UserId


class FirstRole:
    pass


class SecondRole:
    pass
