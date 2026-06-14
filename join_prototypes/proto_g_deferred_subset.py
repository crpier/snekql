"""Prototype G: can pyright enforce a DEFERRED subset constraint refs <= scope,
while ALSO accumulating scope through join()? (Needed to save columns-first.)

To reject `select(User.email, Region.code).join(Order, on=...)` we need, at the
terminal boundary:   RefT (referenced owners)  <:  ScopeT (joined tables).

The self-type trick `def ready(self: Q[X, X, *Ts])` induces that constraint ONLY
for a specific variance: ScopeT contravariant, RefT covariant. But join() must
return Q[ScopeT | New, ...], which puts ScopeT in an OUTPUT position -> covariant.
This file tests whether both can hold at once.
"""
# pyright: reportUninitializedInstanceVariable=false

from __future__ import annotations


class Pending: ...
class User[S = Pending]: ...
class Order[S = Pending]: ...
class Region[S = Pending]: ...


class ReadyB[*Ts]: ...


class JoinOn[A, B]: ...


class QB[ScopeT, RefT, *Ts]:
    # RefT used covariantly (output); ScopeT used... see join below.
    def _refs(self) -> RefT: ...

    # Accumulate scope through joins: ScopeT appears in the RETURN union.
    def join[New](self, on: JoinOn[New, ScopeT]) -> QB[ScopeT | New, RefT, *Ts]: ...

    # Deferred subset check: unify scope and refs through one fresh X.
    def ready[X](self: QB[X, X, *Ts]) -> ReadyB[*Ts]: ...


def check_b() -> None:
    # refs == scope: must be OK
    ok: QB[User[Pending] | Order[Pending], User[Pending] | Order[Pending], int, str]
    ok = QB()
    _ = ok.ready()

    # refs include Region, scope does not: SHOULD error if the check works
    bad: QB[User[Pending] | Order[Pending], User[Pending] | Region[Pending], int, str]
    bad = QB()
    _ = bad.ready()  # want: error

    # legitimate: joined an EXTRA table not referenced (refs subset of scope)
    extra: QB[
        User[Pending] | Order[Pending] | Region[Pending],
        User[Pending] | Order[Pending],
        int,
        str,
    ]
    extra = QB()
    _ = extra.ready()  # want: OK (refs subset of scope, extra join is fine)
