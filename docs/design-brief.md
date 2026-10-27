# snekql design brief

**Status:** Working draft for maintainer review, 2026-10-27. Repository-only design
material, not current usage instructions or an adopted redesign.

This brief records the maintainer's requirements and proposes principles for
reviewing interfaces. It follows the defaults/nullability discussion in #473,
#539 and #583; it does not select their proposed syntax. Tracking: #588.

## Proposed purpose

> snekql makes database query results trustworthy in Python, even when the
> database schema and other writers cannot be taken on trust. It makes that
> database code readable and practical to verify, for humans and coding agents.

Trustworthy means that a successful validated result satisfies its declared
shape. It does not prove that the query answers the right business question,
that every stored row is acceptable, or that structural schema verification is
complete. Static checking, runtime validation and schema verification supply
different evidence; none replaces the others.

Model declarations, writes, testing facilities and schema tools serve this
purpose. Their convenience should not displace query-result trust as the central
reason for the library.

## Maintainer-stated requirements

These are desired outcomes, not claims that all are implemented or supported.

- **R1 — Trust results, not the environment.** Production schemas can be wrong,
  and other applications write to the same database. Establish that returned data
  matches the expected shape; do not silently coerce unexpected data to fit.
  Mismatches must be possible to handle intentionally.
- **R2 — Reading first.** Prefer understandable queries and reviewable changes
  over minimum writing effort. Some mechanical declaration ceremony is acceptable
  if it improves the experience of reading and checking queries.
- **R3 — Humans and agents.** Keep the interface intuitive for humans. Evaluate
  agent use empirically, including comparisons between candidate interfaces.
- **R4 — Pragmatic verification.** Make the library itself and consumer programs
  practical to check through types, focused tests and other useful evidence.
  Reduce dependence on slow end-to-end tests; do not merely add more of them.
- **R5 — Target environments.** Python 3.15+, SQLite and MariaDB; local or remote
  databases on VMs/bare metal, and container-hosted services such as Railway.
  Cloudflare Workers is also desired, but needs a separate feasibility assessment
  of runtime, driver and connectivity constraints, not an assumed support claim.
- **R6 — Data-intensive work.** Help diagnose inefficient SQL during development
  and production. Make useful SQL patterns discoverable to humans and agents,
  including patterns beyond those currently common at the workplace.
- **R7 — Schema evolution.** Support long-lived upgraded installations, fresh
  installations without replaying the full historical chain, potentially
  irreversible stopped-application migrations, feature-flagged data migrations,
  and explicit old/new application-schema compatibility when a rollout requires
  it. Team branch divergence and local branch switching must be tractable.
- **R8 — Application-owned frameworks.** Expose enough coherent model metadata to
  help applications build their own CRUD frameworks, without supplying REST
  endpoint generation as a library responsibility.

The adoption target is the workplace's actual SQLAlchemy workflows, not an
unbounded promise of SQLAlchemy feature parity.

## Proposed design principles

The following are derived proposals, not separately accepted decisions.

### P1. A typed result must earn its type — R1, R4

A validated query must not successfully return data outside its advertised shape.
This includes scalar and structured projections, joins, aggregates, subqueries,
streams and write RETURNING results, not just whole Table Models. A schema check
passing is not permission to skip the data contract. Explicit unchecked reads
must not retain the same trusted static promise.

### P2. Establish a match; do not conceal a mismatch — R1

Distinguish intentional Codec decoding from unwanted coercion. Define permitted
representations and deliberate normalization explicitly; do not guess how to
repair unexpected data. Failure must be distinguishable from a valid NULL or a
missing row, with bounded, useful diagnostics that do not disclose fetched data
or bindings by default. This principle alone does not choose exceptions versus
another error interface.

### P3. Make meaning local and readable — R2, R3

Judge a declaration by the consumer code it enables, not just its own brevity.
Mechanical repetition can be acceptable; duplicated semantic authority and
checker-specific ceremony need stronger justification. Neither verbosity nor
abstraction is inherently a virtue. Optimize for comprehension, review and safe
change rather than for the fewest characters or parameters.

### P4. Offer complementary, affordable checks — R4

Static checks establish program-level facts; pure Query Compilation checks SQL
and bindings without a database; focused Materialization tests challenge data
contracts; backend tests establish execution behavior. Keep these seams usable
without an entire application fixture. Test both valid programs that must remain
accepted and invalid programs/data that must fail, with attributable evidence.
Fast checks complement rather than certify away real backend coverage.

### P5. Keep database work visible — R2, R6

Preserve explicit SQL-shaped operations, Transaction scope and inspectable Query
Compilation. Make timings and native execution plans useful without silently
executing a query as an inspection step. Diagnosis should expose evidence, not
promise automatic optimization. Consider advanced SQL by the useful queries and
verification it enables, not by feature-count competition.

### P6. Accommodate storage without surrendering application contracts — R1, R7

An application can describe a strict subset of the data a database permits. For
example, nullable storage can coexist with a non-null read contract if actual
NULL fails Materialization. Other writers' defaults need not match Python
construction defaults. Keep schema permission, constructor presence, accepted
input values and successful read values conceptually separate; do not choose
public flags or generic arity merely from this distinction.

### P7. Make agent usability falsifiable — R3, R4

Use realistic tasks with explicit semantic oracles, not just successful checker
runs. Assess reading, modification, diagnosis and verification as well as initial
code writing. Record model/tool/doc versions and repeated trials; retain held-out
tasks and human review so hill-climbing does not become benchmark memorization.
Agent patience is not evidence that duplicated facts or obscure code are safe.

### P8. Spend complexity where it buys the purpose — R2–R8

Prefer deep modules with a small coherent interface over configuration that
merely exposes implementation machinery. Account for interacting options,
diagnostics, documentation and maintenance, not only call-site convenience.
Provide supported metadata seams for application-owned frameworks rather than
requiring them to depend on private typing machinery.

## Proposed non-goals

- SQLAlchemy parity, extra database families or every possible deployment target.
- Hidden relationship loading, identity maps, dirty tracking or implicit
  persistence; see the current [non-ORM contract](why-not-orm.md).
- Silent data repair, promises of automatic query optimization or pretending
  backend differences do not exist.
- An included REST/CRUD application framework.
- Choosing public syntax through checker tricks alone, or treating agent benchmark
  scores as sufficient evidence of interface quality.

These are scope proposals, not authorization to remove existing capabilities.

## Decisions still open

1. **Matching and decoding:** which representations and normalizations are
   intentional, which conversions count as unwanted coercion, and how strictness
   is expressed and audited across every result path, including custom validators.
2. **Failure handling:** what information makes contract mismatches actionable,
   how callers recover, and what happens after partial stream consumption or a
   write that completed before RETURNING validation failed.
3. **Model responsibilities:** which facts belong to read, construction and
   physical-schema contracts; whether separate input/read domains are worthwhile;
   which declaration ceremony earns its cost.
4. **Verification and performance:** which focused checks consumers need, how to
   preserve backend fidelity, and how to measure validation cost on representative
   workloads without weakening typed promises accidentally.
5. **Extension and deployment scope:** the metadata seam for external frameworks
   and the feasibility of restricted serverless runtimes.
6. **Compatibility and evolution:** how adopted principles would change existing
   behavior, how users migrate, and which alternatives representative tasks favor.
   Coordinate migration requirements with the work already underway; do not
   design a competing migration system here.

## Representative evaluation tasks

Use the same intent, data and success criteria across candidate interfaces.

| Task | Evidence to examine |
| --- | --- |
| Read an unfamiliar query and predict its shape and database work | Correct explanation, review effort, hidden assumptions |
| Handle wrong storage values, unexpected NULL and query-induced NULL | Correct successes and attributable failures; no concealed coercion |
| Add a join, aggregate or subquery without erasing types | Exact results, valid controls and rejected misuse |
| Make a small consumer change and verify it locally | Type diagnostics and focused tests without an end-to-end fixture |
| Diagnose an inefficient query and try a better SQL pattern | SQL/bindings, safe plan inspection, measured equivalent results |
| Give agents equivalent implementation and repair tasks | Semantic success, verification effort, retries and human review |
| Exercise upgraded, fresh and branch-divergent installations | Explicit schema/data expectations and recovery steps, coordinated with migration work |
| Build an application-owned CRUD helper from metadata | Supported imports, coherent facts and no private-implementation dependency |

For agent comparisons, separate candidate-development tasks from held-out
assessment tasks and vary models/runs. Keep documentation/tool access and budgets
comparable; record time, tool/token cost, failures and uncertainty alongside
successes. Benchmark implementation and runtime experiments require separate
scoping; this brief has not run or certified any of these tasks.

## Relationship to current contracts

[CONTEXT.md](../CONTEXT.md), adopted [ADRs](adr/), the
[compatibility policy](compatibility.md) and current usage guides remain in force.
In particular, today's Logical Type couples construction/read values, and the
Migration Declaration is a canonical linear history with Migrations as schema
creation authority. Desired fresh bootstrap and branch workflows do not select
snapshots, history stamping, migration graphs or a replacement authority.

Current [raw result validation](raw-sql.md) explicitly follows normal Pydantic
behavior, including contract-controlled coercion. Current
[unchecked reads](typing.md) widen their static
results. This brief is not evidence that all current paths already satisfy a new
non-coercion policy, nor permission to change those paths silently.

Use this draft to expose gaps and evaluate proposals. Adopted changes need their
own decisions, compatibility review and validation; this document changes no
interface, schema, deployment support or runtime guarantee.
