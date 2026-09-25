# Historical dual-class research archive

The maintainer selected the lifecycle-generic class-body approach. This branch preserves the alternative input-first dual-class research before class-body migration begins. It is a historical artifact, not a merge candidate, release, or maintained alternative implementation.

Branch: `archive/dual-class-research`

Archived: 2026-09-25

Native baseline: `56dbc32`, snekql 0.7.0, callable foreign-key support.

Production Python code, dependencies, and package configuration are unchanged from that baseline. The root README only adds an archive notice. The experiments remain under `scratchpad/` so their imports, independent typing callers, and recorded source hashes retain their original meaning.

## Start here

1. **Read the strongest application, not the first prototype.** [Direct descriptor application](scratchpad/dual_descriptors/application.py) runs sixteen advanced operations with `UserRow.field` expressions. [Its report](scratchpad/dual_descriptors/README.md) explains the remaining source/materialization adapters and retained failures.
2. **Compare identical work.** [Advanced comparison review](scratchpad/paired_advanced/REVIEW.md), [class-body application](scratchpad/paired_advanced/body.py), and [dual application](scratchpad/paired_advanced/dual.py) compare the same data, operations, SQL, and result requirements. This earlier dual application still spells column conversions explicitly; the direct-descriptor follow-up removes them.
3. **Understand the declaration tradeoffs.** [Input-first declarations](scratchpad/paired_situations/dual.py) and the [revised assessment](scratchpad/paired_situations/VERDICT.md) cover generated identities, defaults, foreign keys, a twenty-field Order, shared behavior, helpers, PATCH/upserts, and navigation. Superseded verdicts remain beside it to show which conclusions changed.
4. **Read the limits before reusing anything.** [Typing/parity matrix](scratchpad/dual_typing_parity/MATRIX.md) and [runtime counterexamples](scratchpad/dual_typing_parity/test_limits.py) distinguish query capability from sound native adoption.

## The alternative being investigated

Input-first dual classes put authoritative storage/default/FK declarations on an input value class. A separate complete row class inherits those fields and refines generated values:

```python
class User(sqlite.Model):
    __row__: ClassVar[type[UserRow]]
    user_id: sqlite.Col[UserId | sqlite.Omitted] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.OMIT
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)


class UserRow(User, sqlite.Row):
    table_name = "users"
    user_id: sqlite.Col[UserId]
```

This is illustrative experimental syntax. See the linked modules for actual imports and runnable declarations. These `sqlite` namespaces are research modules, not the released backend namespace.

The useful properties were ordinary value annotations, inherited methods, exact input-bound helpers, and real `isinstance(value, UserRow)` narrowing. Complete values are also inputs by inheritance. That makes excluding complete rows from insertion a genuine policy/interface conflict, not a missing overload.

The final descriptor experiment reuses native query expressions:

```python
rows = await transaction.fetch_all(
    sqlite.select(
        UserRow.email,
        UserRow.balance.add(3),
        UserRow.nickname.coalesce("anonymous"),
    ).all()
)
assert_type(rows, list[tuple[str, int, str]])
```

It still needs `table(UserRow)` for model sources and a SQLite transaction adapter for public row materialization. Native alias syntax such as `alias.column(UserRow.email)` binds a column to a source occurrence; it is not the removed descriptor conversion.

## What the research established

- The matched advanced queries were effectively a tie at the tested interface level. Declaration layout did not inherently determine query capability.
- Direct dual descriptors can preserve exact native expression types without call-site conversions in the tested applications.
- Descriptor identity matters. A forwarding proxy failed native alias checks; canonical native column identity fixed the tested cases.
- Native storage/codecs, deferred FK binding, and query compilation can be reused. This did not require a second application query builder.
- Independent callers, clean controls, exact `assert_type` assertions, diagnostic locations, source hashes, and actual database execution exposed failures that annotated function returns alone concealed.

The class-body choice does not turn the dual experiments into failed proofs. Class-body offers one storage declaration and a shorter native-adoption path. Dual offers simpler ordinary value-class behavior. The maintainer chose class-body; the archived evidence remains bounded by what was actually checked.

## What remained unresolved

- **Materialization was not safe to ship.** A native transaction could accept a translated model query yet return private native instances instead of the promised public dual row. The SQLite bridge decoded them; the MariaDB scalar controls did not solve model results.
- **Model sources still needed translation.** Native `select(UserRow)` was not established.
- **Typing was incomplete.** Required wrong-target FK declarations, malformed witnesses, generated-field refinements, and some default factories retained holes or unsupported forms. Shared native query holes remained too.
- **The prototypes were not one finished design.** Earlier adapters had different query, backend, join, and projection contracts. Their successful observations cannot be combined into an imaginary complete implementation.
- **Operational coverage was bounded.** One two-thread binding test is not a concurrency audit. Full codec/configuration coverage, performance, the entire transaction facade, and streaming cancellation remained outside the completed work.

Complete does not mean persisted. Defaulted does not mean database-owned. Nominal IDs do not prove authorization or existence. snekql remains a query builder/runtime, not an ORM.

## What is included

Four complete study directories retain their code, independent caller inventories, reports, tests, and runners:

| Study | Historical evidence |
| --- | --- |
| `dual_descriptors` | 156 typing observations, 65 runtime tests, five MariaDB cases, sixteen matched query algorithms/SQL pairs |
| `paired_advanced` | 236 observations, 61 tests, sixteen matched advanced operations |
| `dual_typing_parity` | 262 observations, 39 tests, fourteen matched SQL/parameter pairs |
| `paired_situations` | 163 original and 225 dual/body observations, 22 source edits, 280 tests, thirteen MariaDB cases |

Counts overlap across studies. They are not a combined score or a count of independent guarantees. Accepted counterexamples, unsupported forms, Unknown/Any, checker failures, and runtime rejection are not static rejection evidence.

Only required implementation modules and explanatory READMEs from supporting studies are included. These cover storage, binding/finalization, backend ownership, implicit pairing, basic SQL, earlier query/value classes, and declaration controls. Their older standalone suites are not archived in full. Body and nested controls remain where the matched comparisons import or execute them; nesting is historical, not a renewed proposal.

Omitted: the class-body adoption/source-contract study, unrelated CRUD/framework research, broad declaration-alternative and recursive-query inventories, most superseded standalone suites, temporary generators, local logs, caches, server data, and environment files. The unarchived local research was preserved rather than deleted.

`scratchpad/ARCHIVE_MANIFEST.sha256` inventories the selected research files and their hashes. The baseline commit supplies native code and the existing lockfile.

## Reading historical statements

Original study files are preserved without rewriting their conclusions. Statements such as "local, uncommitted", old working-branch names, or "next integration work" describe their research-time state, not this published archive or an approved roadmap. This guide records the final disposition.

Older reports saying descriptor integration was unfinished predate `dual_descriptors`. Model-source and materialization work still was unfinished. Earlier constructor-led or incomplete-query verdicts are explicitly superseded by the later matched comparison.

Supporting READMEs may mention files, runners, logs, or broader studies omitted from this subset. Only the four complete study runners above are reproduction entrypoints for this archive. Absolute paths and temporary caller locations in stored reports identify the original execution; they are not installation instructions.

## Reproduce

Use a normal clone/checkout with a real `.git` directory, not a linked worktree whose `.git` is a file. The original runners place temporary probes and database data under `.git`. Keep the checkout path short enough for Unix socket limits.

The recorded environment used Python 3.14.2, ty 0.0.77, Ruff 0.16.5, snektest 0.16.0, and MariaDB 12.3.2. Install the development environment with the baseline lockfile and provide the MariaDB server tools required by the retained integration tests. The lockfile pins ty; exact interpreter/server versions still matter.

```sh
uv sync --locked
sha256sum --check scratchpad/ARCHIVE_MANIFEST.sha256

bash scratchpad/dual_descriptors/run.sh
bash scratchpad/paired_advanced/run.sh
bash scratchpad/dual_typing_parity/run.sh
bash scratchpad/paired_situations/run.sh
```

The runners regenerate JSON reports, so absolute paths and temporary locations can dirty a checkout even when behavior matches. Verify the manifest before rerunning. Do not globally redirect native typing-test `TMPDIR` into the checkout; historical diagnostic-path checks were sensitive to that.

The descriptor suite intentionally emits the native `LexicalDatetimeWarning` for plain datetime-over-Text comparison. It was not suppressed as a success criterion.

## Archive validation

The selected files were exported into an isolated checkout with its own environment installed by `uv sync --locked`. No omitted local study was available there. The checkout retained native baseline Git provenance.

All four complete runners passed:

- Direct descriptors: 156/156 observations, 65 tests, matched algorithms/SQL/scaffolds.
- Advanced comparison: 236/236 observations, 61 tests, sixteen matched algorithms/SQL pairs.
- Typing/parity: 262/262 observations, 39 tests, fourteen SQL/parameter pairs.
- Original situations: 163/163 and 225/225 observations, 22 source edits, 280 tests, scaffold/SQL/navigation checks.

Each runner also passed its ty, Ruff, and formatting checks. The isolated checkout passed the native fast suite with 1,127 tests, repository ty/Ruff/format checks, and archive integrity checks. Full native integration tests were not run.

The first native fast run had one environment error because the temporary export had no Git HEAD, so its environment report could not identify a source commit. Giving it the actual baseline provenance resolved that error; no test or production code was changed. The expected descriptor datetime warning remained visible.

The original reports are archived unchanged. Reproduction regenerated reports only inside the isolated checkout. Before publication, every recorded source hash in the five primary typing reports was checked against the selected files or native baseline.
