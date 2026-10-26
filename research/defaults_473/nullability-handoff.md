# Agent prompt: investigate model types versus SQL nullability

Investigate potential improvements to how **snekql declares SQL nullability**, with brownfield database adoption as a primary requirement. This is research and recommendation, not authorization to implement a production redesign.

Repository: `crpier/snekql`, currently checked out at `/home/crpier/Projects/third-snekql`. Use that checkout for discovery; create your own worktree for changes.

## Maintainer context

The current declaration:

```python
value: db.Col[str | None] = db.Text()
```

makes the SQL column nullable because the logical Python annotation includes None. The Python constructor argument remains required. Adding `default=None` permits constructor omission; it does not declare SQL DEFAULT NULL. For resolved annotations, an explicit `nullable=` currently acts as a consistency assertion that must agree, not an independent schema override.

The maintainer is uncertain whether the Python field type should determine the SQL schema. Investigate that coupling rather than assuming either that annotation-derived nullability must stay or that every mismatch must become legal.

Brownfield projects can have multiple database writers. The Python model's policy and the database's policy need not coincide. In the related defaults discussion, the maintainer now considers an interface change worthwhile and favors separate Python/SQL defaults for flexibility. For example, this proposed declaration is meaningful, not contradictory:

```python
value: db.Col[bool] = db.Integer(default=False, server_default=True)
```

Python construction supplies False; other INSERT writers omitting the column receive the SQL default True. The public `server_default` parameter is still a proposal, not an implemented feature. Do not mistake older research recommendations favoring no change for the latest maintainer preference. No final public spelling or full implementation contract is selected.

Separate defaults illustrate independence, but do **not** prove that arbitrary nullability/type combinations are sound. Preserve truthful types and explicit failure semantics.

## Workflow and scope

1. Read repository AGENTS.md instructions. Work in your own branch/worktree from current origin/main; another agent is continuing defaults research on `research/473-default-declarations`. Preserve that agent's work rather than stashing or editing it. Query GitHub context using `gh issue view 473` and `gh pr view 539`.
2. Read the current implementation and relevant ADRs, then document the existing contract with source references. That baseline is complete when you can distinguish schema nullability, Python input acceptance, constructor omission, pending generation, and successful Row decoding.
3. Compare a **small shortlist**, including unchanged behavior, an explicit schema declaration, and any justified intermediate policy. Use scenario-first examples with all options together. Avoid an open-ended naming exercise.
4. Test proposed static guarantees at the declaration/construction and consumer-typing seams, using TDD and independently clean positive controls with exact negative diagnostics. Those seams are already agreed for this research. For any additional seam, propose it and obtain confirmation before adding tests.
5. Deliver a dated report and a recommendation. Identify which constraints should remain, which can safely be relaxed, and which require a separate write/read contract or explicit validation policy. Follow the repository's research PR workflow; do not merge.

**Static-only:** read source and run local typing/parser checks. Do not import or execute model templates, factories, generated callers, INSERT/DDL/database workflows, or SQLite/MariaDB runtime suites. Distinguish source-supported existing behavior, native checker evidence, intended semantics, and untested runtime obligations. Do not change dependencies or production code. GitHub Actions are disabled: validate locally, without waiting for them. Do not reopen the abandoned annotation-left / SQL-right generated-constructor approach.

## Questions the report must answer

- Is the annotation the domain of Python constructor inputs, successfully decoded Row values, or both? How does that relate to the values permitted by the database schema?
- Should `nullable=` be authoritative, inferred, or an assertion? What should omission of that option mean? Explain compatibility and migration costs.
- Can an application intentionally model a subset of the database's possible values? If so, how are externally written incompatible values handled: selection restrictions, decoding failures, explicit transformations, or a different read type? Never claim a non-null Row merely because Python constructors reject None.
- Conversely, should Python input admit None when SQL rejects NULL? Is there a meaningful transformation/omission policy, or just an error deferred to INSERT? Keep explicit NULL distinct from requesting a default.
- What information belongs in schema generation and verification? Describing an existing schema must not imply permission to alter it.
- What changes, if anything, for defaults, generated values, codecs, outer joins, primary/foreign keys, and backend-specific constraints? Separate SQL NULL from JSON null and PENDING_GENERATION.

## Scenario sheet

For each scenario, show declarations, accepted/rejected constructor inputs, omission behavior, exact Pending/Row types, expected SQL nullability, decoding behavior for externally written NULL, and intended verification outcomes. Label conclusions not established by static evidence.

Include:

1. Required non-nullable input with a NOT NULL schema.
2. Required nullable input with a nullable schema.
3. Nullable input with a Python None default: omission differs from requiredness, not SQL nullability.
4. Nullable input with a non-None Python default; explicit None remains distinct.
5. A nullable database column whose application model wants non-null values, including an external writer actually storing NULL.
6. Python input admitting None against a NOT NULL database column.
7. Server defaults, including DEFAULT NULL, with explicit None versus omission; do not confuse a default with a nullability constraint.
8. GenCol[T] versus GenCol[T | None]: pending generation is not SQL NULL.
9. Query-induced nullability from outer joins, independent of base-column NOT NULL.
10. Primary-key and foreign-key constraints, JSON null versus SQL NULL, and representative SQLite/MariaDB differences.

Audit **accepted incoherence** as well as rejected mistakes. Accurate constructor types alone do not establish that every possible database row can be decoded. If a combination is intentionally restricted, explain the relevant guarantee rather than labeling all differences invalid.

## Starting references

- `snekql/model.py`: `_validate_column_nullability`, declaration binding, and population.
- `snekql/storage.py`: `nullable_declared`, `nullable`, annotation resolution, codecs and validation.
- `snekql/sqlite/model.py`, `snekql/mariadb/model.py`: Col/GenCol and lifecycle typing.
- `snekql/_value_decode.py`, `snekql/_materialization_shape.py`: decoding and query-induced nullability.
- `snekql/sqlite/_schema_ddl.py`, `snekql/mariadb/schema.py`, `snekql/_schema_shape.py`: schema compilation/verification.
- `docs/typing.md`, `docs/typing-compatibility.md`, `docs/schema-drift.md`.
- `docs/adr/0005-storage-primitive-constructors-with-derived-codecs.md`.
- `docs/adr/0007-server-defaults-as-default-markers.md` (there is another ADR numbered 0007).
- `docs/adr/0008-separate-partial-schema-verification.md`.
- `docs/adr/0019-callable-foreign-key-binding.md`.
- `docs/adr/0020-class-body-models-with-pending-and-row.md`, plus relevant cross-references.

Related defaults artifacts are on `origin/research/473-default-declarations`, not necessarily main. Read them with `git show` or through the draft PR rather than checking out another agent's branch:

- `research/defaults_473/scenarios.py` — scenario-first visual document; deliberately unchecked, not direct typing evidence.
- `research/defaults_473/review-sheet.md`, `shortlist-comparison.md` — prior scenario evidence; earlier rankings predate the latest brownfield emphasis.
- `research/defaults_473/callable-intersections.md` — a newer stock-ty prototype permits common server/identity omission without repeated pending defaults. Its research-only `required=True` override means Python constructor input is required, NOT SQL NOT NULL. This is a checker-sensitive alternative with trusted protocol declarations, not a selected public interface or runtime implementation.
- `research/defaults_473/implicit-server-omission.md`, `native-omission-hooks.md` — earlier limitation probes and release-pinned source analysis. The annotation-sensitive goal of inferring C1 requiredness solely from Col versus GenCol remains unfulfilled; do not mistake the new alternative for that exact rule.
- `tests/research/test_default_declarations.py` — exact paired typing helper.

Use the installed, pinned ty and snektest; run focused research checks and `uv run ty check`, `uv run ruff check .`, and `uv run ruff format --check .`. Do not mistake green tests that record accepted limitations for successful implementations. The final report must separate **the best design** from **whether its benefits justify its change cost**.
