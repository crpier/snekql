# Structured API security review — 2026-10-10

Tracking: maintainer-requested hardening pass, #449. This is a source review and
regression-test record, not a security certification or a CVE assessment.

## Scope and method

Reviewed built-in query construction/rendering, schema generation, connection
setup, and default query/validation diagnostics. Tests use the agreed public
boundaries: query factories and compilation, native Transactions, scaffold and
configuration, and representations/errors/warnings/telemetry. Confirmed changes
were driven by failing public behavior tests before implementation.

The upstream historical review focused on patches, not vulnerability counts:

- Django's [JSON-key fix](https://github.com/django/django/commit/7deeabc7c7526786df6894429ce89a9c4b614086),
  [alias fix](https://github.com/django/django/commit/93cae5cb2f9a4ef1514cf1a41f714fef08005200),
  [EXPLAIN-option fix](https://github.com/django/django/commit/6723a26e59b0b5429a0c5873941e01a2e1bdbb81),
  and [connector fix](https://github.com/django/django/commit/98e642c69181c942d60a10ca0085d48c6b3068bb)
  show that keys, names, and selectors must retain their structured meanings.
- SQLAlchemy's [literal-execution audit](https://github.com/sqlalchemy/sqlalchemy/commit/4eba6997dc0f4cd103d47bbc78a5aafaf0c137b1),
  [default escaping fix](https://github.com/sqlalchemy/sqlalchemy/commit/079df65dc0f71ea4d1771b6ae17e13242c766517),
  [password stringification change](https://github.com/sqlalchemy/sqlalchemy/commit/3333c6623fa45bcbc7fabd061184a79b7b7f2fa6),
  and [parameter-hiding option](https://github.com/sqlalchemy/sqlalchemy/commit/4b321e8a5e6b728a818a801c3ad90bb759c584bc)
  distinguish safe execution and incidental disclosure from explicit inspection.

## Reviewed paths and outcomes

| Area | Paths | Outcome |
| --- | --- | --- |
| Values and syntax | `expressions.py`, `_query_compile.py`, `_value_encode.py`, `_value_expression.py`, backend dialect fragments | Built-in values use bindings; selector vocabularies are private/bounded. MariaDB query identifier quoting now additionally escapes the driver's percent-format layer. |
| Names and query composition | `model.py`, `_aliases.py`, `_cte.py`, `_output_label.py`, `_output_layout.py`, `query.py` | Names are validated or dialect-quoted; typed output references use identity rather than parsing names as raw SQL. Native tests exercise punctuation-bearing projection names alongside bound values. |
| DDL and defaults | `_schema_compile.py`, `_schema_plan.py`, `_checks.py`, `_server_defaults.py`, `indexes.py`, `constraints.py`, backend storage/schema modules | Bounded literal rendering and index-prefix validation already exist. Decimal dimensions now require native integers. Scalar foreign-key actions now validate the supported vocabulary for direct and deferred targets. |
| Connection setup | Backend configs/settings/runtime, MariaDB pool/TLS code, temporary-server password bootstrap | Required settings use fixed statements; credentials use driver connection options. Password representations omit passwords. Existing bootstrap code pins only its short-lived client session's SQL mode before quoting password data; stale limitation documentation was corrected. |
| Diagnostics | `_compiled.py`, `_raw.py`, `_telemetry.py`, `_observation.py`, `_named_projection.py`, `errors.py`, `storage.py`, shared/backend runtime | Existing inspection/telemetry redaction retained. Builder execution tracebacks now suppress driver causes by default. Built-in model errors and typed JSON extraction omit values. Boundary validation hides input rendering. Primitive/JSON serialization type mismatches fail without warnings or value-bearing causes. MariaDB cursors no longer forward server warning text. |

## Compatibility and limits

Default builder `ExecutionError.__cause__` is no longer the native driver error.
Use `.failure` for portable classification. Deliberate unsafe `values` visibility
retains driver chaining and bound-value rendering. `.params` remains explicit
inspection data under both policies. Model validation messages intentionally
lose value-bearing Pydantic detail; exception types remain unchanged.

No restrictions were added to query intent, caller-authored raw SQL, or migration
bodies. No row-level authorization or SQL sandbox was introduced. Application
Python callbacks and custom SQL renderers remain trusted code. Lifecycle and
migration errors, database-native logs, source literals, and traceback tools that
collect locals are not covered by a blanket confidentiality claim.

See [security boundaries](security.md) for the ongoing review checklist. Test
files added by this pass are `tests/query/test_security_boundaries.py` and
`tests/runtime/test_security_diagnostics.py`. Existing foreign-key integration
tests now check portable failure evidence rather than native exception chaining.

## Validation

Environment: Python 3.15.0, SQLite 3.53.1, MariaDB 12.3.3, with the locked project
environment. Native MariaDB tools were supplied through an existing local
installation; no dependency or system-package changes were made.

The first full-suite attempt exhausted the pre-existing `/tmp` allocation quota
while creating fresh InnoDB fixtures. A project-local temporary directory also
changed isolated typing-probe behavior because it lay inside the ignored checkout
path. The final validation uses a dedicated temporary directory outside the
checkout on the home filesystem. Existing retained test databases were not
removed.

Results on the final source state:

| Check | Result |
| --- | --- |
| `uv run snektest tests` with native MariaDB tools and external `TMPDIR` | 3,779 passed; four CLI shutdown tests timed out in the background runner. |
| Foreground rerun of `tests/testing/mariadb/test_password_literals.py::cli_environment_password_authenticates` with the same native tools and `TMPDIR` | All four passed. |
| `uv run ty check` | Passed. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed, 514 files. |
| `uv run python scripts/generate_query_overloads.py --check` | Passed. |
| `git diff --check` | Passed. |

Together the final full-suite run and foreground rerun passed all 3,783 collected
cases. The background shell inherited ignored `SIGINT` (confirmed from the
runner's signal disposition), so its CLI children could not honor the shutdown
signal tested by those four cases. No CLI implementation changes were made to
accommodate this harness condition. The final CLI rerun ran without another
MariaDB fixture suite in parallel and passed in 28.11 seconds. Only temporary
server processes created by this validation were stopped; unrelated servers and
existing retained databases were left alone.
