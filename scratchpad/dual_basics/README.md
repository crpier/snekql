# Basic SQL: complete settings saves

Local, uncommitted research on `research/dual-basic-sql`, based on main `56dbc32`.
Continuation of [research issue #396](https://github.com/crpier/snekql/issues/396),
which is closed. This study does not reopen, update, or publish to it.
Production code and dependencies are unchanged.

## Question

Can the agreed `User` / `UserRow` declarations support an ordinary settings
upsert while keeping constructor requirements, database defaults, conflict
ownership, and returned values clear? What basic SQL should we cover before
resuming aliases and nullable source occurrences?

Start with:

- [examples.py](examples.py): storage models, complete form, trusted actor,
  explicit response, and `save_settings`.
- [tour.py](tour.py): first save, a separate digest-schedule change, repeat save,
  and a refetch. No visible transaction adapter or Schema argument.
- [BASIC_SQL.md](BASIC_SQL.md): prioritized basic SQL cases and existing controls.
- [current.py](current.py) and [test_current.py](test_current.py): native-interface
  declarations and execution controls for the same conflict/default semantics.

```sh
bash scratchpad/dual_basics/run.sh
# Tour only:
uv run python -m scratchpad.dual_basics.tour
```

The disposable tour uses SQLite in memory. Failure tests use an automatically
removed file database under `.git` because native failure handling can discard
connections. A replacement in-memory connection does not retain the old schema.

## Application spelling

These are research exports, not released snekql interfaces.

```python
class User(sqlite.Model):
    id: sqlite.Field[int | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Field[str] = sqlite.Text(unique=True)
    password_hash: sqlite.Field[str] = sqlite.Text()


class UserRow(User, sqlite.Row):
    table_name = "users"
    id: sqlite.Field[int]
    create = sqlite.insert_using(User)
```

A bare row annotation removes the inherited constructor default, retains storage
metadata, and must preserve the logical type except for removing `Omitted`.
Tests cover ordinary generated fields, required nullable values, and generated
FK refinement with its relationship retained. Wrong logical refinements remain
runtime errors; `ty` still accepts the recorded counterexample.

The input contract is not generally partial. `User` can contain an explicit ID.
`UserRow(...)` requires complete values but does not prove database existence.
The row marker is the previous study's tested marker under the new public name.
Historical examples keep their original naming. MariaDB has not been moved to
the new spelling or annotation-only handling in this study.

## The realistic upsert

`UserSettings` has a FK primary key on `user_id`, required notification/timezone
settings, and a generated `digest_hour` with database default 9.
`UserSettingsRow` narrows `digest_hour` to a required `int`.

```python
async with database.transaction() as transaction:
    settings = await transaction.execute(
        UserSettingsRow.create(
            user_id=actor.user_id,
            email_notifications=request.email_notifications,
            timezone=request.timezone,
        )
        .on_conflict(
            UserSettingsRow.user_id,
            action=sqlite.DoUpdate(
                UserSettingsRow.email_notifications.to_inserted(),
                UserSettingsRow.timezone.to_inserted(),
            ),
        )
        .returning()
    )
```

The first save inserts. A repeat save updates only the two named columns and
returns a complete `UserSettingsRow`. A digest schedule changed elsewhere to 18
stays 18. There is one row per user. No preliminary SELECT decides whether to
INSERT or UPDATE.

`save_settings` validates an IANA timezone off the event loop and constructs an
explicit response containing only the editable settings. Requests forbid a
client-supplied `user_id` and require both editable values. `Actor` represents
trusted context supplied by a caller; this is not an authentication implementation.
The password-hash strings in tests/tour are opaque fixtures, not password hashing
or usable credentials. Never implement registration by overwriting credentials
on an email conflict.

### Omission is not PATCH

The executable counterexample seeds `digest_hour=18`, omits that field in the
attempted INSERT, then adds `digest_hour.to_inserted()` to `DoUpdate`. SQLite
updates the stored hour to **9**, the database default. The native control does
the same thing.

Omitting a value from INSERT does not mean preserving it during conflict UPDATE.
Only the explicit assignment list provides that preservation here. The complete
settings request is not a PATCH contract. This is SQL behavior, not a defect in
the dual declaration design or a dual-specific benefit.

### Conflict and result contracts

- `column.to_inserted()` uses that column's attempted insert value.
- `column.to(value)` makes a literal conflict assignment with the same owner.
- `DoUpdate` requires at least one assignment from the inserted model.
- Single and composite conflict targets execute. The composite control updates
  one user's matching device without changing the other device.
- Without RETURNING, execution yields `None` on both insert/update branches.
- `DoNothing` inserts if possible and skips a conflict. It also returns `None`;
  that return does not distinguish inserted from skipped.
- Public `DoNothing` commands have no `returning()` method. The private wrapped
  command still delegates to the native rejection if reached through erasure.
  This intentionally does not introduce an optional RETURNING row contract.
- Wrong model/family targets and assignments reject in isolated typing probes
  and after type erasure at command construction.
- Native SQL handles the operation; no second SQL compiler or new codecs.
- `.compile()` exposes the native `CompiledQuery`; runtime values remain bound.
- FK/unique failures are not swallowed by `DoNothing`. A real later constraint
  failure rolls back an earlier successful upsert in the same transaction.
- Static column ownership does not establish a valid unique conflict target.
  A same-model, nonunique target type-checks and fails when SQLite executes it.

## What is still adapter code

`runtime.py` is a small composition facade over the existing native Database.
It yields the existing research Transaction internally, hiding tour boilerplate.
Native code still owns connections, commit, rollback, SQL execution, and codecs.
This is not production integration or an alternative runtime implementation.
Only initialization, context lifetime, migrate, and default transactions are
exposed. Savepoints, configuration/telemetry options, transaction options, and
schema-verification forwarding are not covered by this facade.

Shared changes in `dual_backends/core.py` add conflict assignments, immutable
conflict plans, terminal ignore commands, write SQL inspection, and native
lowering. Its SQLite ForeignKey constructor now forwards `primary_key`.
Literal and attempted assignments currently share a conflict-only carrier. A
future ordinary UPDATE adapter needs a distinct attempted-value restriction;
old and new research write adapters are not an interchangeable public interface.

Earlier namespace examples and typing observations still pass. No historical
study was renamed wholesale, and the shared finalizer was not changed.

## Evidence

- **38 isolated typing observations**: 16 capabilities, 19 rejections, and three
  accepted counterexamples. Clean controls and challenge-line diagnostics are
  required. Source hashes and checker versions are in `results.json`.
- **34 tests**, including three independent native-interface runtime controls.
  Test files separate declarations, application contracts, conflict execution,
  erased guards, and native controls.
- **1,127 existing fast tests** and the **three native SQLite upsert runtime tests**.
- All seven previous research runners passed: backend namespaces, finalization,
  storage, declaration alternatives, recursive CTEs, queries, and features.
- Repository `ty`, Ruff lint/format, and tracked diff checks passed.
  No complete integration or performance suite is claimed.

Accepted static counterexamples:

1. A nonunique, same-model conflict target.
2. Copying an omitted server-defaulted field during conflict update.
3. Changing the logical type in an annotation-only row refinement.

A diagnostic-runner note: redirecting all native test temporary directories
inside the checkout exposed the existing typing CLI's absolute-versus-relative
filename matching assumption. It produced 19 infrastructure failures, not new
static guarantees. The normal fast-test command passed all 1,127. Logs retain
both runs; production test tooling was not modified.

Useful red and validation logs are under `.git/dual-basics/`. The early public
inner-command escape from the ignore wrapper was caught with a failing typing
probe, then made private. This is conventional Python privacy, not a sandbox.

## Next

Review this settings example before expanding implementation.
[BASIC_SQL.md](BASIC_SQL.md) proposes ordinary read cardinality and narrow public
user projections first, then targeted UPDATE and DELETE. Sorting/filtering,
aggregates, bulk writes, and MariaDB semantic controls follow before aliases.
No aliases, nullable occurrences, recursive CTEs, or new mapping helper were
added here.
