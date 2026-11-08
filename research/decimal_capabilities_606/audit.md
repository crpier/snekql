# Independent evidence audit (#606)

2026-11-08, after the initial consumer/report implementation.

The reviewer reran the focused consumer checks and inspected the overlay, fixtures
and historical failures. It found no import/suppression problem making the reported
Decimal consumer results falsely green, and considered the distinction between
conditional propagation and sound storage discovery appropriately explicit.

One medium finding: the global Comparable/Attr receiver constraints also regress
ordinary non-Decimal columns, not just the legacy Decimal spelling. A temporary
`sqlite.Col[int] = sqlite.Integer()` probe rejected `.gt(1)` and `.sum()` under the
overlay. Calling other data types merely untested understated the evidence.

Parent response: preserved those exact counterexamples in `known_holes.py.txt`.
The baseline-versus-overlay characterization now checks that both calls pass before
and fail after the overlay; README explicitly reports the broader regression. No
production fix or expansion of the overlay was attempted. No follow-up delegate was
started for this small correction.

This audit is not an endorsement of the experimental interface. False capability
claims, column-comparison bypasses, aggregate-predicate regressions, missing native
Decimal arithmetic and whole-overlay typing failures remain documented blockers.
