# Per-operation deadlines fail closed

Transaction I/O uses a fresh Operation Deadline for begin, each query or stream
interaction, cursor cleanup, commit, and rollback. Backend Configs keep
`acquire_timeout` and `operation_timeout` separate; an explicit
`transaction(timeout=N)` overrides both for that Transaction. Application code
between driver calls is not timed.

A timed-out driver call makes the physical connection unsafe. Query Runtime
rejects further use and asks the Backend Runtime Adapter to discard it rather
than rollback or return it to the pool. Commit timeout is reported as ambiguous.
Rollback timeout during an existing application failure is logged and discarded
without replacing the application failure.

## Alternatives

- **One deadline for the complete Transaction.** Rejected because time spent in
  application code would consume a database-I/O budget and make cleanup fail for
  reasons unrelated to the database.
- **Acquisition timeout only.** Rejected because a checked-out connection could
  hang forever in statement execution or transaction control.
- **Server-side statement limits only.** Rejected as the sole mechanism because
  SQLite and MariaDB expose different controls, and those controls do not cover
  cursor, commit, rollback, or driver failures.
- **Return a timed-out connection after rollback.** Rejected because cancellation
  can race the driver's physical operation; neither transaction state nor wire
  protocol synchronization is known.

SQLite detaches an unsafe connection from reusable pool state immediately and
closes it asynchronously. Its pool capacity remains occupied until physical
close finishes, so no replacement can exceed the configured bound. MariaDB
closes the socket before releasing the driver's pool slot.
