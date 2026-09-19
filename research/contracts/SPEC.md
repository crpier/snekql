# Equivalent runtime contracts

Research for #358. Approved boundaries: full snekql transactions, SQLAlchemy ORM
sessions, model construction, raw SQL, migration execution, and schema inspection.
No package fixes. Prior research PRs remain independent.

An order has generated ID, price_cents in 0..9999999999, quantity in
1..2147483647, status defaulting to pending in the database, and created_at
defaulting to the database clock. Application integer input must be an actual int,
not bool, str, float, or Decimal. Explicit timestamp input must be aware and
normalizes to millisecond UTC. Explicit None is invalid, not a default request.

Use integer cents deliberately. Decimal representation, tax rounding, overflow of
aggregates, currencies, and full commerce modeling are outside this round.

Record where invalid input fails. Read successful writes in a new transaction or
ORM session, so identity-map reuse cannot masquerade as database decoding.
Exercise ORM flush rather than only type processors. Record default timing and
whether the original pending object changes. Keep raw SQL probes distinct from
application validation. Do not classify infrastructure errors as data rejections.

SQLAlchemy may use custom types and Pydantic validation. snekql may use literal,
committed migration SQL with extra constraints. Neither solution may silently
weaken the target or conceal strict schema-verification failures. Observe
verification with constraints removed and a changed literal default, too.

Completion: real SQLite and temporary MariaDB runs; retained models, migrations,
SQLAlchemy DDL, installed schemas, values/types/errors, focused tests, and a report
of explicit decisions and maintenance obligations. No numeric ergonomics scores.
