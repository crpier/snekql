# Temporary MariaDB Test Server

`snekql.testing.mariadb` provides local throwaway MariaDB process management for integration tests. It is test-support infrastructure, not production or development database provisioning.

## Python API

```python
from snekql import Database
from snekql.testing.mariadb import temporary_mariadb_server

async with temporary_mariadb_server() as server:
    config = server.config()
    database = await Database.initialize(logger, config, models=[User])
```

The context manager starts an unprivileged local `mariadbd`, waits until it is ready, creates the requested test database, yields connection details, and stops the server when the context exits.

The default database name is `test`. Unix socket transport is enabled by default. TCP must be requested explicitly:

```python
async with temporary_mariadb_server(transports={"unix_socket", "tcp"}) as server:
    socket_config = server.config()
    tcp_config = server.config(transport="tcp")
```

When both transports are enabled, `server.config()` and `server.run_sql()` prefer Unix socket. Requesting a disabled transport raises `TemporaryMariaDBServerError`.

## Auth policies

Two auth policies are supported:

- `auth="insecure"` uses MariaDB grant-table bypass. This is the default and is only safe for isolated local throwaway tests.
- `auth="password"` enables username/password credentials. If no password is provided, snekql generates one for the server run.

Password auth can be used with Unix socket transport, TCP transport, or both. MariaDB's OS-user-based Unix socket authentication plugin is not supported.

## Data directories

Data directories are retained after shutdown so failed tests can be inspected.

- If `data_directory` is omitted, snekql creates a retained directory under the system temp directory and exposes it on the yielded server.
- If `data_directory` is provided, snekql initializes it when missing or empty and reuses it when it already looks like a MariaDB data directory.
- `clean_before_start=True` is valid only with an explicit `data_directory`; it deletes that directory before initialization.

snekql never deletes a data directory when the server stops.

Because MariaDB data directories are large, spawning many temporary servers with the default retained system-temp location can fill `/tmp` or hit a filesystem quota. MariaDB may then fail during initialization with InnoDB preallocation errors such as `error 122`. In long-running test workflows, prefer an explicit `data_directory` that the test fixture deletes after shutdown, periodically remove stale retained directories such as `/tmp/snekql-mariadb-*`, or reuse an explicit `data_directory` with `reset_database=True`.

## Database reset

For retained data directories, `reset_database=True` drops all base tables from the configured test database after startup and before yielding the server:

```python
async with temporary_mariadb_server(
    data_directory=Path(".snektest/mariadb-data"),
    reset_database=True,
) as server:
    ...
```

The yielded server also exposes the same operation as an explicit fixture cleanup helper:

```python
await server.reset_database()
```

Resetting the database is incompatible with `clean_before_start=True`; choose one reset strategy per server startup. `clean_before_start=True` rebuilds the whole data directory, while `reset_database=True` reuses the existing data directory and removes only application tables from the configured database.

## SQL helper

The yielded server exposes a public async SQL helper for test setup and diagnostics:

```python
result = await server.run_sql("SELECT 1")
failing = await server.run_sql("SELECT * FROM missing_table", check=False)
```

`run_sql` shells out to the `mariadb` client and returns `MariaDBCommandResult` with `returncode`, `stdout`, and `stderr`. It accepts raw SQL only; application queries should use `Database.initialize(..., server.config())`.

## Foreground CLI

Install the package, then run:

```sh
snekql-mariadb-server
```

The command starts a foreground Temporary MariaDB Test Server, prints one ready-to-copy `mariadb` command per enabled transport on stdout, and keeps running until Ctrl-C.

```sh
snekql-mariadb-server --transport unix_socket --transport tcp --auth password
```

For password auth, stdout commands use `-p` and the generated or provided password is printed to stderr. The CLI does not accept a direct password argument; use an environment variable when deterministic credentials are needed:

```sh
SNEKQL_MARIADB_PASSWORD=test \
  snekql-mariadb-server --auth password --password-env SNEKQL_MARIADB_PASSWORD
```

Extra `mariadbd` arguments can be passed with repeatable `--server-arg=...`. Managed options such as data directory, socket, port, bind address, networking, grant-table bypass, and error-log settings are rejected because snekql owns those parts of the test-server contract.

## Requirements

The helper requires these external binaries unless custom paths are supplied:

- `mariadbd`
- `mariadb-install-db`
- `mariadb`

To use `server.config()` with `Database.initialize`, install the existing MariaDB runtime extra:

```sh
uv add 'snekql[aiomysql]'
```
