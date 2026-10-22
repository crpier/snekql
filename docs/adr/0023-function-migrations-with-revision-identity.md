# Run Python migration functions and track revision identity

Individual migrations are async Python functions receiving a managed migration
context. Callers own preconditions, backfills and external actions; snekql owns
connection coordination, per-revision transaction completion and history.
Initialization remains connect-only, and history verification, partial structural
verification and application readiness remain distinct caller-composed steps.
This replaces the SQL-string bodies and checksums described in ADRs 0001/0002
and their history-v2 amendments; the execution and cleanup guarantees still apply.

History identifies an ordered revision ID, not its Python implementation.
Source hashing cannot capture imported helpers, configuration or external files;
we choose explicit revision identity over a misleading behavior fingerprint.
Applied functions and their helpers are immutable by convention. Editing one
under an applied ID neither reruns it nor raises an error. Corrections require a
new revision. Prefix/head validation still rejects unknown or divergent history.

There are no deployed databases requiring compatibility: remove SQL-string
support, legacy adoption and history conversion. Unsupported history fails
closed. SQL plans cannot be predicted from arbitrary Python without executing
it, so read-only plans list pending IDs and do not offer SQL preview.

Functions execute only when pending under the backend's migration coordination.
Contexts permit parameterized SQL execution and native tuple fetching on the
managed connection, not pool access or caller-controlled commit. They expire
when the function exits and reject work from other tasks. SQLite database effects
and history are atomic per function; MariaDB DDL can commit implicitly. Neither
backend rolls back arbitrary Python effects or promises exactly-once external
work. Failed or interrupted functions require application-specific replay review.

Initial DDL generation remains development-time scaffolding: review and freeze
its output inside functions, never regenerate deployed migrations from current
models during execution. See issue #475.
