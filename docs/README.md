# snekql guides

New here? Start with [your first query](getting-started.md). It is a complete
SQLite script you can copy and run without a server.

## Learn the basics

Read these in order, or jump to the task you have now:

1. [Getting started](getting-started.md): install, create a table, insert, and read.
2. [Models](models.md): describe columns, defaults, and Pending/Row values.
3. [Queries](queries.md): filter, sort, insert, update, and delete.
4. [Connections and transactions](transactions.md): commit, roll back, stream, and close.
5. [Migrations](migrations.md): keep database changes in reviewed SQL.

[Why not an ORM?](why-not-orm.md) explains what snekql deliberately leaves out.
[Choosing storage](storage.md) covers Python values versus database types.

## Write more involved queries

- [Joins, aliases, and subqueries](joins.md)
- [Arithmetic, text functions, and CASE](expressions.md)
- [Named results and RETURNING](results.md)
- [CTEs](ctes.md), [UNION](unions.md), and [recursive queries](recursive-ctes.md)
- [Integer literals](literals.md) for constants in named query results
- [Raw SQL](raw-sql.md) and [reporting recipes](reporting.md)
- [Inspect SQL and query plans](inspecting-queries.md)

## Run an application

- [Web services, workers, and database fixtures](service-recipes.md)
- [Check a schema against your models](schema-drift.md)
- [Adopt an existing database](migration-baselines.md)
- [Change a schema while deploying application versions](rolling-migrations.md)
- [Recover an interrupted migration](migration-recovery.md)
- [Handle errors and decide whether a retry is safe](error-handling.md)
- [Database settings and TLS](engine-settings.md)
- [Connection replacement, credential rotation, and shutdown](connection-lifecycle.md)
- [Pool measurements, logging, and OpenTelemetry](telemetry.md)
- [Run a temporary MariaDB server for tests](testing-mariadb.md)

## Look up a detail

- [API reference](api-reference.md): operations and every public export
- [Backend support](backend-capabilities.md): SQLite/MariaDB differences
- [Typing reference](typing.md): exact result types, declarations, and helper annotations
- [Type-checker support](typing-compatibility.md): use ty; Pyright and mypy have gaps
- [MariaDB versions](mariadb-support.md)
- [Optional JSON fields](optional-json.md)

## Upgrade or evaluate a release

- [Upgrade to 0.8's class-body models](class-body-migration.md)
- [Migrate older binary UUID data](binary-uuid-migration.md)
- [Release checks and adoption checklist](adoption.md)
- [Compatibility policy](compatibility.md) and [changelog](../CHANGELOG.md)
- [Tested failures and environments](failure-matrix.md)

## Work on snekql

Start with [contributing and local checks](contributing.md).

Design records explain decisions; they are **not current usage instructions**:

- [Architecture decisions](adr/)
- [Class-body proposal](class-body-interface-proposal.md)
- [Query composition design](query-composition-design.md)
- [Earlier schema compatibility audit](schema-compatibility-audit.md)

[Back to the project README](../README.md)
