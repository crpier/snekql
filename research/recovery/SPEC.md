# Updates and recovery comparison

Research for #363. No package changes or literal-default design decisions.

## Public interfaces

The user approved real snekql transactions and SQLAlchemy ORM sessions, update
builders and attribute assignment, independent reads, and raw external corruption.
Research tests call the public observation runner using those interfaces.

Two engines: isolated file-backed SQLite and temporary socket-only MariaDB.
Two libraries. Two tracks: native declarations and explicit validation policy.

## Shared task

Two rows have unique codes, positive integer quantities, nullable notes, and an
aware timestamp. Row 1 starts with quantity 1, code 'one', and note 'keep'.
Row 2 has code 'two'. No generated values or literal defaults are involved.
Database schema matches for constraints: primary key, unique code, NOT NULL on
quantity/time, nullable note. Neither track adds a quantity CHECK. External SQL
can therefore demonstrate read validation without disabling database controls.

Native snekql declares constrained quantity and UtcDatetime. Native SQLAlchemy
uses ordinary integer and datetime types, without custom validation. This is not
equivalent application policy. The validated track adds a shared strict-positive
integer patch validator before each library's write interface, plus a SQLAlchemy
result validator for quantity. It does not repair SQLAlchemy timezone semantics.
Do not attribute added policy to either library's defaults.

## Desired outcomes, not assumed library behavior

- Invalid quantity updates must not persist. Record the rejection stage.
- Updating quantity alone preserves note; explicitly setting note=None clears it.
  Explicit quantity=None must fail. An empty patch is not tested.
- A committed valid update is visible through a fresh transaction/session.
- An exception escaping a transaction must roll back earlier writes.
- Catching a database error inside a transaction may have different semantics.
  Observe read/write reuse and whether earlier writes commit. Do not equate a
  failed ORM flush with a direct statement error.
- After rollback, inspect retained objects without triggering implicit async IO;
  explicitly refresh ORM objects. Independently verify database contents.
- A fresh transaction/session must remain usable after a failed operation.
- External invalid quantity should be rejected during validated materialization.
  Observe native behavior independently. Record raw injection failures separately
  from decode failures. Malformed and naive timestamps probe the read policy too.

No savepoints, concurrent writers, retries of ambiguous commits, deadlocks,
network failures, all SQLAlchemy bulk paths, or performance claims. Characterize
only observed operations. Test-first checks anchor runner behavior; study outcomes
may disagree with the desired contract without being package bugs.
