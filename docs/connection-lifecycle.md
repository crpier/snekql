# Connection lifecycle

## Driver audit

This policy was checked against aiomysql 0.3.2 and aiosqlite 0.22.1.

- aiomysql scans idle sockets for EOF, reader errors, and its extra EOF marker.
  It does not actively ping them. Its `pool_recycle` uses time since cursor
  creation, not physical connection lifetime or time since pool return.
- aiomysql's default `ping()` can reconnect the same connection object. That
  would invalidate snekql's record of verified session settings. Active health
  probes therefore use `reconnect=False` and discard a failed connection.
- aiomysql's native connection initializer catches `Exception`, not native
  cancellation. snekql owns the connection object before awaiting its handshake
  and closes it on any failed or interrupted initialization. The pool exists
  before network I/O, so the acquisition deadline covers authentication too.
- aiomysql does not wake `wait_closed()` when releasing an already closed socket.
  snekql first waits for its admitted operations to return, including discarded
  connections and interrupted opens, then finishes driver shutdown.
- aiosqlite queues work on a connection's worker thread. Cancelling a caller is
  not proof that queued work stopped. SQLite keeps unsafe cleanup owned and does
  not treat a connection returned during shutdown as physically closed.

The private aiomysql pool adaptation is shared by ordinary and required-TLS
connections. The driver dependency remains constrained to `>=0.3.2,<0.4`.
Recheck socket ownership, stale-reader detection, TLS, and shutdown when widening
that range. The adaptation does not patch global driver behavior.

## Replacement and recovery

See [engine settings](engine-settings.md#connection-recycling-and-health) for
`max_connection_lifetime`, `max_connection_idle`, and `health_check`.

Recycling and replacement happen before a Transaction begins. Fresh MariaDB
connections authenticate again and apply and verify the required session
settings. A server restart can invalidate idle sockets and active Transactions.
An idle socket may be replaced on checkout; active work is never replayed.

A checkout probe can fail even after TCP connection establishment. That
acquisition fails and discards its connection. The application may start a fresh
Transaction later. A successful health probe cannot guarantee the next operation
will succeed. Use [failure classification and commit outcomes](error-handling.md)
to decide whether whole-transaction retry is appropriate. An unknown commit
outcome requires reconciliation, not blind replay.

SQLite replacements reapply the configured durability policy. Replacing an
in-memory connection loses that database's contents. Neither backend reconnects
an active Transaction onto a new physical connection.

## Credential rotation and whole-pool replacement

Config is immutable. Each Database keeps its original credentials and TLS
context for future connections. Recycling does not refresh a password, reload
certificates, or consult a credential provider.

Use a new Database for new credentials, certificates, or endpoint configuration:

1. Provision the replacement credentials and grants. Prefer an overlap period
   where both identities are valid.
2. Construct a new Config and `await mariadb.Database.initialize(new_config)`.
   This establishes connectivity and verifies engine settings. It does not
   migrate or verify the application's schema. Run any application readiness
   checks before handover.
3. Publish the replacement through the application's connection-routing logic.
   Synchronize this handover with request admission. Stop creating Transactions
   from the old Database.
4. Let existing work finish, then `await old_database.close()`. Keep ownership of
   both Databases until each is either published or closed. If publishing fails,
   close the unused replacement.
5. Revoke the old credentials after old work drains. Do not route requests back
   to the old Database merely because its cleanup timed out.

For example, `dataclasses.replace(current_config, password=rotated_password)`
creates a new Config without mutating the old one. Initializing that Config also
creates a fresh TLS context from its configured certificate paths. snekql does
not perform the application routing step or mutate an existing pool in place.

Changing the password of the same database user may leave already authenticated
sessions usable, but the old pool can no longer open replacements. Account
revocation can also interrupt active work. Do not assume an overlap period unless
the database's account policy actually provides one.

Queued or created-but-not-entered Transactions still reference their original
Database. They are not moved to the replacement and may receive
`DatabaseClosingError`. Application shutdown must account for these requests,
not just checked-out database connections.

## Graceful shutdown

Stop admitting requests and finish or cancel application-owned work deliberately
before closing its Database. Exiting a Transaction commits clean work or rolls
back an exception; `Database.close()` does not decide how application work should
finish and does not forcibly kill active Transactions.

Both backends use an owned shutdown task. Concurrent close callers join it.
Native cancellation of a waiting caller does not abandon physical cleanup or
reset its deadline. A later `close()` can join it or retry failed cleanup.
Unobserved shutdown failures are logged.

- MariaDB starts irreversible driver shutdown and rejects new work. A timeout or
  failed driver close leaves it unavailable for new Transactions. Calling
  `close()` again may finish cleanup, but cannot reopen that Database. Failed
  idle sockets stay owned for another close attempt.
- SQLite can resume accepting work after a timeout waiting for active leases,
  provided no failed physical cleanup remains. Failed idle or discarded handles
  stay owned, and new work remains rejected until cleanup succeeds. One failed
  idle close does not skip the other idle connections.

`acquire_timeout` supplies the shutdown wait budget. It is not a force-close
mechanism. In particular, SQLite physical cleanup can wait on worker-thread I/O
beyond that budget. Keep the event loop alive while owned cleanup runs; cancelling
a waiter or exiting the process is not evidence that resources were closed.

A successful close is idempotent and future work raises `DatabaseClosedError`.
See [shutdown error behavior](error-handling.md#close-lifecycle-and-retry-semantics) for the
backend-specific timeout contract.
