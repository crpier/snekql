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

**Backend Namespace**:
The public database-family namespace that owns model bases, column declarations, and runtime configuration for one database family.
_Avoid_: generic portability layer, driver module

**Backend Runtime Adapter**:
The internal adapter that lets the Query Runtime acquire connections, control transactions, compile SQL, and materialize rows for one backend.
_Avoid_: ORM session, universal dialect abstraction

**Temporary MariaDB Test Server**:
A local throwaway MariaDB server managed by snekql test-support APIs for integration tests and short-lived CLI sessions.
_Avoid_: development database, production database, MariaDB provisioning

**Temporary MariaDB Test Server Auth Policy**:
The access model chosen for a Temporary MariaDB Test Server: insecure grant-table bypass or password credentials.
_Avoid_: Unix-socket authentication, production authentication, account management

**Temporary MariaDB Test Server Transport**:
The local connection path exposed by a Temporary MariaDB Test Server: Unix socket by default, local TCP when explicitly requested, or both when requested together.
_Avoid_: authentication policy, network service

**Server Default**:
A database-supplied column value that is filled in by the database when an insert omits that column.
_Avoid_: Python default, constructor default

**Pending Model**:
A model instance constructed by application code before it has been materialized from the database.
_Avoid_: Draft, unsaved entity

**Fetched Model**:
A model instance materialized from database query results by the Query Runtime.
_Avoid_: Loaded, read model, entity
