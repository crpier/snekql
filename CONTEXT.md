# snekql

snekql is a library for declaring relational data contracts and executing typed SQL-shaped operations against a database. It exists to give Python applications an explicit query layer and runtime without becoming an ORM.

## Language

**Query Builder**:
The layer that declares relational data contracts and builds typed SQL-shaped operations.
_Avoid_: ORM, repository

**Query Runtime**:
The layer that executes built queries against a database and manages database-backed execution concerns.
_Avoid_: ORM session, persistence layer

**Database**:
An initialized snekql runtime service that owns database connectivity, schema startup work, and transaction entry.
_Avoid_: Pool, uninitialized database config

**Transaction**:
A database transaction exposed directly through the library as the unit within which reads and writes are executed.
_Avoid_: Unit of Work, session

**Table Model**:
A Python class that declares a table's row contract and serves as an ergonomic front end over the query builder's schema model.
_Avoid_: Entity, ORM model

**Dialect**:
The database-specific SQL and schema behavior targeted by compilation and verification.
_Avoid_: Driver, runtime

**Server Default**:
A database-supplied column value that is filled in by the database when an insert omits that column.
_Avoid_: Python default, constructor default

**Pending Model**:
A model instance constructed by application code before it has been materialized from the database.
_Avoid_: Draft, unsaved entity

**Fetched Model**:
A model instance materialized from database query results by the Query Runtime.
_Avoid_: Loaded, read model, entity
