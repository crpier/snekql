# Feature coverage

Current means the native lifecycle-generic interface at `56dbc32`, not the body
witness shim. Existing dual means the input-first adapter used by dual.py in the
paired tour. Reuse means this study's SQLite bridge, including its documented
consumer and inference holes. A blank implementation is not a typing impossibility.

| Feature | Existing dual | New evidence / limit |
| --- | --- | --- |
| Precise INSERT and model/scalar SELECT | Works | Rechecked against native; exact input/row and nullable value types |
| Required fields, nominal IDs, explicit NULL | Works | Constructors and wrong-ID callers reject in both |
| Server-default omission and row narrowing | Works with refinements | Omitted refinement fails binding, not declaration checking |
| State-neutral methods/helpers | Simpler | Plain self and input-bound generic helpers work; tested native spellings need union/protocol alternatives |
| Runtime class narrowing | Works | UserRow is distinguishable; native generic specialization is not an isinstance target |
| Input-only insertion, excluding complete rows | Does not exclude rows | Conflicts with accepting User while UserRow remains its subtype |
| Result-link correctness | Runtime guard | Both accept wrong links statically; native result witness also has a runtime mismatch |
| Python defaults checked against literals | Missing | Small typed Text alternative proves repair possible |
| Model/column source separation | Stronger than native control | Inputs and instances rejected by existing dual source signature |
| Backend-family isolation | Works in bounded namespaces | SQLite/MariaDB model, column, JSON and Decimal controls; bridge remains SQLite-only |
| Wrong predicate/assignment/FK owners | Bounded coverage | Native-reuse cases preserve native rejections; ordinary eq_col right-owner hole remains |
| Query Readiness | SELECT supported | Reuse preserves SELECT/UPDATE/DELETE requirements and rejects incomplete consumption |
| Scalar and tuple results | Scalar only | Reuse has exact scalar/tuple results and real readback |
| Positional width | No tuple interface | Reuse inherits native eight-slot ceiling; older dual query design supports ten variadic slots |
| Wide named results | Missing | Native-reuse nine-field exact type; native named-result machinery reused |
| Named keyword correctness | Not provided | Runtime validation in native/reuse; dual classes do not infer keyword schemas |
| INNER model joins | Only root model returned | Reuse appends actual dual models like native joins |
| LEFT model joins | Missing | Reuse produces tuple[UserRow, PostRow or None], with actual absent-row readback |
| Projection LEFT JOIN | Missing | Native/reuse both reject; older explicit nullable-role design demonstrates another typing contract |
| Aliases and self-joins | Missing here | Reuse executes native roles; wrong role, model-column and mutation target reject |
| ORDER BY, DISTINCT, LIMIT, OFFSET | Missing | Exact reuse typing and actual ordered pagination |
| Aggregates, GROUP BY, HAVING | Missing | Exact count/sum types; grouped named results execute |
| Arithmetic, CASE, COALESCE, text functions | Missing | Reuse typing; arithmetic/CASE/COALESCE execute |
| Scalar/IN/EXISTS subqueries | Missing | Scalar/IN/correlated EXISTS typing; scalar and correlated EXISTS execute; inline bridge conversion retains a known Any hole |
| Nonrecursive CTEs and typed labels | Missing | Exact native-reuse results; CTE executes |
| UNION and UNION ALL | Missing | Both type-check precisely; UNION ALL executes |
| Recursive CTEs | Missing | Native operator reused with exact callback depth/result checks and execution; earlier dual recursion regression covers richer graphs |
| Typed UPDATE/DELETE | String-field native bridges | Reuse checks owners, values and readiness; actual returning rows |
| Generated-column / primary-key updates | Native bridge | Reuse remains writable like current GenCol; generation is not immutability |
| INSERT / UPDATE / DELETE RETURNING | Whole single INSERT | Reuse has model/scalar/named types with correct cardinality; model/named runtime tests |
| Bulk INSERT RETURNING | Missing | Reuse executes exact list[UserRow]; mixed-model batches remain runtime-checked in both |
| Conflict updates | Works | Rechecked; explicit update executes. DoNothing stays non-returning policy, not optional rows |
| Exact-one / zero-or-one reads | fetch_all workaround | Reuse supports both and rejects optional scalar consumption |
| Streaming | Missing | Exact dual-row batches execute; nominal ChunkStream identity and unchecked flags not wrapped |
| validate=False | Missing | Read/write overloads widen to object; raw read does not claim dual-row identity |
| Validated raw SQL | Missing in facade | Native raw Summary contract executes on dual-declared storage. Independent of table-model layout |
| Query Compilation inspection | Bounded | 14 matching native/reuse SQL and ordered-parameter pairs |
| Decimal, UUID, JSON, temporal codecs | Earlier bounded evidence | Existing paired MariaDB tests rerun; this bridge does not prove complete codec parity |
| Scalar/self/mutual/composite FKs, actions | Earlier bounded evidence | Paired and older feature regressions; query layout does not itself fix native binding/precision limits |
| CHECK, partial/prefix indexes, schema verification | Earlier storage evidence | Not reimplemented or exhaustively integrated here. Metadata work remains, not a demonstrated typing obstruction |
| Migrations, savepoints, deadlines, telemetry, pooling | Native runtime capabilities | Bridge executes inside a native Transaction; complete facade/configuration parity not claimed |
| MariaDB locking and backend write restrictions | Missing / bounded | Native for_update types checked; no MariaDB version of this advanced bridge. SQLite work does not prove MariaDB parity |
| Native nominal Model helpers | Different base/protocol | Cannot migrate unchanged. Result-only helpers often survive, but source erasure needs care |
| Windows, INTERSECT, EXCEPT | Not current builder features | Do not count these as lost native features. Raw SQL is a separate route |
| Truly database-owned/computed columns | Not a current GenCol promise | Prior timestamp discussion is separate. Adding a row-only field is not enough to implement read-only SQL metadata or insertion policy |

Some backend/composition documentation still describes recursive builders as future
work. The exported recursive operator, independent current-native callers, and
runtime tests establish that it is implemented on this baseline. No production
documentation was changed for this study.

## Where guarantees stop

The reuse experiment establishes representability and execution for its listed
cases. It does not establish safe drop-in integration. In particular, using its
queries with a plain native Transaction returns a different class than the phantom
result annotation promises. The bridge also needs prebound columns for reliable
scalar inference. Both failures have retained accepted caller and runtime evidence.

The native query interface can keep its source, role, result, backend and readiness
coordinates while the value classes change. The work not solved here is making
that declaration/materialization seam sound and preserving the full supported
interface in both backends. No claim of language-level impossibility follows from
that unfinished integration.
