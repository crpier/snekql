# Per-backend-namespace column declarations

Each Backend Namespace declares its own column type classes (`Integer`, `Real`,
`Text`, `Blob`, `Json`, `Boolean`, `DateTime`) — `snekql/storage.py` for SQLite
and `snekql/mariadb/storage.py` for MariaDB — even though the two sets are
currently identical. This is deliberate: per CONTEXT.md a Backend Namespace
"owns model bases, **column declarations**, and runtime configuration for one
database family," and the per-namespace class is the seam where backend-specific
storage behavior will diverge as it appears (e.g. a MariaDB `VARCHAR` length, a
backend-specific `server_default`, or knobs a future backend needs). Collapsing
the classes into one shared set would erase that seam and force future
divergence through conditionals or break the per-namespace declaration API.

This records the decision so architecture reviews do not keep re-proposing the
collapse on the grounds that the classes are byte-identical today: identical-now
is what an anticipatory seam looks like before its first divergence.

## Considered Options

- **Collapse into one shared set of column classes re-exported by each
  namespace.** Rejected: it measures today's duplication, not the seam's
  purpose, and contradicts the documented Backend Namespace ownership of column
  declarations. The SQLite namespace re-exporting the shared classes today is a
  convenience, not the target design for both.
- **Keep separate classes per namespace.** Chosen. The cost is real but bounded
  (the classes restate the same `__new__`/`build_attr` shape), and it is the
  natural place for backend storage behavior to differ without leaking
  conditionals into shared code.

## Consequences

- The two class sets must be kept in sync by hand until they diverge; a change
  to the shared column contract touches both files.
- One genuine cleanup remains and is **independent** of this decision: the
  shared `AttrConfig` exposes a SQLite-specific field, `sqlite_storage_class`
  (a `Literal["INTEGER", "REAL", "TEXT", "BLOB"]`), which the MariaDB classes
  must still populate even though MariaDB maps its DDL off the backend-neutral
  `storage_type_name` instead. Renaming that field to a backend-neutral name
  would remove the leak that makes the duplication *look* redundant, without
  merging the per-namespace classes.
