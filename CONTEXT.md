# snekql

snekql is a library for declaring relational data contracts and executing typed SQL-shaped operations against a database. It exists to give Python applications an explicit query layer and runtime without becoming an ORM.

## Language

**Query Builder**:
The layer that declares relational data contracts and builds typed SQL-shaped operations.
_Avoid_: ORM, repository

**Query Runtime**:
The layer that executes built queries against a database and owns connection acquisition, transaction lifecycle, and result materialization.
_Avoid_: ORM session, persistence layer

**Materialization**:
The Query Runtime's read-side conversion of database result values into the result shape promised by a select query. For a table-model select, materialization produces a Fetched Model; for scalar or tuple selects, it produces decoded Python values.
_Avoid_: hydration, insert encoding, write compilation

**Database**:
An initialized snekql runtime service that owns database connectivity, schema startup work, and transaction entry.
_Avoid_: Pool, uninitialized database config

**Transaction**:
A database transaction exposed directly through the library as the unit within which reads and writes are executed.
_Avoid_: Unit of Work, session

**Table Model**:
A Python class that declares a table's row contract and serves as an ergonomic front end over the query builder's column declarations and storage metadata.
_Avoid_: Entity, ORM model

**Dialect**:
The database-specific SQL compilation behavior — parameter placeholders, identifier quoting, and value encoding — targeted by the Query Builder when compiling queries.
_Avoid_: Driver, runtime

**Schema Drift**:
A mismatch between a Table Model's declared schema and the live database schema, discovered during the Database's schema startup verification.
_Avoid_: migration, schema evolution

**Schema Policy**:
The Database initialization choice of how Schema Drift is handled at startup: strict raises, warn logs and continues.
_Avoid_: migration strategy, runtime toggle

**Backend Namespace**:
The public database-family namespace that owns model bases, column declarations, and runtime configuration for one database family.
_Avoid_: generic portability layer, driver module

**Backend Runtime Adapter**:
The internal adapter that lets the Query Runtime acquire connections, compile SQL, and materialize rows for one backend; transaction control runs on the connections it yields.
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

**Generated Column**:
A column whose value the database produces (auto-increment or Server Default), declared with `GenCol`: its value may be Missing on a Pending Model but is always present on a Fetched Model.
_Avoid_: computed property, Python default

**Missing**:
The sentinel marking a Generated Column value that is not available yet on a Pending Model; inserts omit Missing values so the database can fill them.
_Avoid_: None, NULL, empty value

**Pending Model**:
A model instance constructed by application code for write-side query building.
_Avoid_: Draft, unsaved entity, materialized model

**Fetched Model**:
A Table Model instance produced by materializing a table-model select result.
_Avoid_: Loaded, read model, entity
