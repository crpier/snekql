# Class-body versus input-first dual classes

Updated after the [advanced paired application](../paired_advanced/README.md).
The previous assessment is preserved in [PRE_ADVANCED_VERDICT.md](PRE_ADVANCED_VERDICT.md).
Nesting is no longer a candidate.

## Assessment

**The advanced query comparison is a practical tie at the interface level.**
Both approaches support the tested model and scalar joins, aliases, expressions,
aggregates, subqueries, CTEs, stored-graph recursion, bulk operations, typed writes,
optional reads, conflict updates, and streaming with exact result contracts.
Sixteen application algorithms and their SQL/ordered parameters match.

I would no longer use the old dual adapter's missing query operations to favor
class-body. The new bridge demonstrates those operations without replacing native
query machinery. It does not establish a safe drop-in implementation.

My earlier narrow class-body preference is now specifically a preference for one
declaration and less adoption work. It is not a claim of better query ergonomics.
If input-compatible complete values and simpler shared methods are what you want,
dual is a reasonable choice. The advanced examples do not undermine that preference.

## The differences worth deciding on

| Concern                               | Class-body                                                                 | Input-first dual                                                    |
| ------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Storage declarations                  | One class                                                                  | Input owns storage; row refines generated fields                    |
| Existing twenty-field Order           | 20 field annotations                                                       | 20 plus 3 refinements                                               |
| Ordinary input-or-complete annotation | User[Pending] or User[Fetched]                                             | User                                                                |
| Complete value annotation             | User[Fetched]                                                              | UserRow                                                             |
| Shared methods                        | Explicit lifecycle-aware self in tested methods                            | Ordinary inherited methods                                          |
| Generic value helpers                 | Union-bound type variable plus structural access can preserve exact result | Input-bound generic can read fields directly                        |
| Runtime class narrowing               | Generic specialization is not an isinstance discriminator                  | Ordinary UserRow class check                                        |
| Insert a complete value               | Rejected                                                                   | Accepted by subtype relationship                                    |
| Wrong declared result witness         | Runtime declaration guard                                                  | Runtime pair/binding guard                                          |
| Query-source misuse                   | Inherited native instance/specialization holes                             | Existing dual source checks reject input classes/instances          |
| Typed Python defaults                 | Native constructors check them                                             | Existing factory loses the check; partial typed repair demonstrated |
| Native query/runtime adoption         | Already integrated                                                         | Materialization and descriptor integration remain                   |

Body's original nominal Model[Pending, Read] helper still erases results. Its
InsertableModel helper is exact, as is the dual Paired helper. Compare those
working alternatives rather than crediting only dual with a new helper interface.

Both erroneous result witnesses pass ty, but body validates its own fetched target
at declaration. The original native wrong-read-model runtime counterexample is
therefore not a dual advantage over this body shim.

## Remaining limitations

The advanced dual application uses explicit native table/column conversions and a
Transaction adapter. Inlining some conversions loses precision. Worse, a plain
native Transaction accepts the translated query but returns private native objects
rather than the promised dual rows. These are confirmed bridge failures requiring
integration work. They are not evidence that two value classes cannot support
native queries, and they are not safe to leave as documentation caveats in a release.

Named projection keywords, source-erasing helpers, right-hand eq_col owners, and
mixed-table bulk inputs retain shared limitations. The tested nullable CTE comparison
needs its nullable operand on the left in both versions. Older dual projection
experiments offer other query contracts, but this comparison does not silently
combine every prototype into a finished implementation.

The original twelve situations still establish storage/default/FK/navigation
tradeoffs. The advanced continuation adds sixteen operations with 236 isolated
typing observations and 61 runtime tests. New advanced runtime work is SQLite;
the earlier thirteen MariaDB tests were rerun, not expanded into a new MariaDB bridge.

## Recommendation

Settle whether complete values should be input-compatible. Then compare one
storage declaration against simpler ordinary value classes and shared helpers.
Treat native adoption cost separately from that interface preference.

For implementation research, investigate a sound native materialization and
descriptor seam rather than another query builder. Keep production lifecycle
generics unchanged until a design is selected and the remaining typing/runtime
contracts are resolved. Neither prototype is approved to ship.
