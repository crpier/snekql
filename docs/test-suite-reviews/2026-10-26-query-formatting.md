# Independent query-formatting oracles

Date: 2026-10-26. Issue: #571, under #536. Fourth bounded slice; the broader
audit remains open. This is an oracle-quality/maintenance change, not a speedup.

## Authorization and scope

Base: `65c553f3773935ee36c733cccb27edab421e98e3`, the authorized squash merge of
#582. The merged tree was verified equal to that PR's validated tree before this
branch started. Its historical full validation is not substituted for this
branch's validation.

The maintainer explicitly extended the pre-agreed seams from public Query
Builder construction/`compile()` and focused snektest selections to public
`repr()`, `str()`, and `inspect()`. These inspect user-visible SQL, binding
redaction/counts, explicit values, and error presentation. They do not prove
native execution, transaction effects, schema validity, or live-backend isolation.

The implementation changes only `tests/query/test_sql_repr.py`. Its six existing
names/markers and the `User` model's complete class AST are retained. SDK files,
runtime/native fixtures, other tests, default selection, dependencies and
Hypothesis budgets are unchanged. #570's native lifecycle/setup work remains
outside this unit. Authorization to merge #582 does not authorize this next PR.

## Finding and replacement contracts

The bare-query case compared formatting of equivalent newly built queries with
itself and checked for `SELECT`. Those comparisons **do protect consistency**;
they are not literally the same object/expression observation. But deterministic
wrong output containing `SELECT` passes. The revised case checks two independent
fresh queries against known SQL/text. It retains two `repr` and two `str`
evaluations and adds two default `inspect()` checks against the same independently
specified multiline result. Determinism is retained by implication, not discarded.

Other cases borrowed SQL/count expectations from the same compiler they were
formatting, or checked fragments of explicit inspection. Those checks had useful
relationships, but could agree on incorrect output. Their public relationships
remain: each explicit `.compile()` result and its corresponding display now have
independent expected SQL and bindings. Expected redaction counts come from the
worked example, not `len(observed_params)`. No expected value is obtained from
SDK output, private query state, or a formatting helper.

| Existing case | Original contract | Retained / strengthened oracle |
| --- | --- | --- |
| `repr_renders_parameterized_select_sql` | SQL from codec appears in compact repr; one binding is `(18,)` | Literal compiled SQL and `(18,)`; compact repr contains the same literal SQL and `<redacted:1>` |
| `explicit_inspection_includes_inlined_form` | Both headings, parameterized email comparison, inlined email and age appear | Entire known parameterized SQL, ordered values tuple, blank-line/headings and approximate inlined example; includes all five original fragments |
| `composed_query_repr_reflects_final_state` | Rebinding retains age/email clauses and compiled SQL appears in repr | Exact SQL includes both clauses in order; `(18, "a@b.com")`; full matching repr with count two |
| `bare_select_repr_renders_sql` | Two fresh repr/str results agree and repr contains `SELECT` | Both equivalent fresh queries independently match literal SQL/repr/redacted multiline text; default inspection matches that text |
| `update_and_delete_repr_render_write_sql` | Each write's codec SQL/count matches its repr | Each public compiled SQL and binding tuple are literal-checked, and corresponding repr uses counts two/one |
| `insert_repr_renders_values_sql` | Insert codec SQL/count matches its repr | Literal public INSERT SQL, `("a@b.com", 18)`, and matching repr with count two |

Five explicit codec calls (two SELECT, three write) become five public compile
calls with identical query inputs. No observation is cached/shared across cases;
no formatting evaluation is removed. In particular, this slice does not try to
save work by dropping the second equivalent bare query. No cross-test import
count reduction is claimed: the removed `tests.helpers.SQLITE_CODEC` dependency
is support, not an import from another test module.

The exact known diagnostic examples deliberately pin the documented compact /
multiline / explicit-value forms. They are not a universal SQL canonicalizer or
an assertion that every valid SQL rewrite is forbidden. An intentional display
contract change needs corresponding expectation review; independently specified
fixtures avoid silently following a compiler regression.

## Red/green and fault calibration

One existing case was strengthened at a time. Each revised case first rejected
a seeded fault in an owned source snapshot, then passed after SDK restoration;
the live checkout's SDK never contained a mutation. Six pairs of red/green
commands cover bare output, common SELECT source, explicit values, composed
reads, update bindings and insert bindings.

The subsequent calibration contains 43 commands using real installed snektest:

| Fault / selection | Original result | Revised result |
| --- | --- | --- |
| Zero-binding repr becomes deterministic `SELECT unavailable` | All six pass | Bare case fails; five remain healthy |
| Zero-binding multiline SQL becomes deterministic `SELECT unavailable` | All six pass | Bare case fails; five remain healthy |
| Common SELECT compiler emits wrong table name | All six pass because borrowed expectations agree / fragments remain | Four read/inspection cases fail; both write cases remain healthy |
| Explicit values output drops displayed tuple | All six pass | Explicit inspection fails; five remain healthy |
| Explicit inlined output appends junk | All six pass | Explicit inspection fails; five remain healthy |
| Common UPDATE compilation reverses binding tuple | All six pass; count stays the same | Write case fails; five remain healthy |
| Common INSERT compilation reverses binding tuple | All six pass; count stays the same | Insert case fails; five remain healthy |
| Default redaction count is off by one | Original select/write/insert cases fail | All five default-format cases fail; explicit values remains healthy |
| Default fallback includes compilation exception text | Existing privacy/error case fails; six normal cases pass | Same result with unchanged privacy case |
| Explicit inspection swallows compilation errors | Existing explicit-error case fails; six normal cases pass | Same result with unchanged error case |
| Select healthy write alone under wrong SELECT source | Not needed for replacement | One selected case passes despite unselected failures |
| Select explicit values alone under default count fault | Not needed for replacement | One selected case passes despite unselected failures |
| Empty executable search path | Not needed for replacement | All 50 formatting/privacy/compiled-query cases pass |

Every SDK mutation is restored and its original selection rerun successfully.
Seeded failures are named `AssertionFailure`s with zero report errors or teardown
failures; all reports are retained. Six separate tracer red results are expected
failures, not passing validation. Empty `PATH` demonstrates no executable search
is required by this selection, not comprehensive absence of possible I/O.

These are local fault-rejection comparisons, not a repository-wide mutation
score or demonstrated product defect. Other compilation/runtime tests already
protect some seeded paths. The current SDK satisfies every new expected value.

## Keep-as-is decisions and boundaries

- `test_safe_inspection.py` is byte-identical. Secret handling, both backend
  families and seven query shapes, explicit per-call locality, logging, opaque
  raw text, unsafe value representations, invalid visibility, fixed fallback
  diagnostics and explicit error propagation remain distinct controls. New SQL
  goldens do not substitute for these security/error checks.
- `test_compiled_query.py` remains byte-identical: public structured inspection,
  immutability, encoding, backend identity and the prohibition on executing
  compiled inspection output have independent contracts.
- `test_query_codec.py` retains the actual private adapter-contract tests,
  including both backend dialects, write encoding, materialization and registry
  behavior. Removing a private shortcut from public-formatting tests is not a
  blanket rejection of appropriate lower-level tests.
- No shared declaration extraction, generic golden framework, snapshot updater,
  renderer wrapper, native fixture or local runner is introduced. The existing
  public model declaration and query construction inputs remain unchanged.

## Validation and reproducibility

- Before/after formatting/privacy/compiled-query group: **50 passed each**,
  comprising six formatting, 24 privacy/error, and 20 compiled-query cases.
- Before/after query directory: **673 passed each**. Forced-lazy query selection:
  **673 passed**, with identical names/markers.
- Frozen normal full suite: **4,267 passed**, zero failures/errors or
  fixture/session teardown failures; wall **399.814795472 seconds**.
  This is validation, not matched performance evidence. All full case names and
  markers match the prior validated #582 tree. Final code hashes match this new
  run; that historical run is only an inventory comparison, not borrowed success.
- No full forced-lazy or direct forced-lazy child-interpreter run is claimed.

Commands set `PYTHON_CONTEXT_AWARE_WARNINGS=1` and retain normal signal
dispositions. Examples:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_sql_repr.py tests/query/test_safe_inspection.py \
  tests/query/test_compiled_query.py --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --json-output
```

Full validation used a private owned tmpfs root, `/dev/shm/sqa-y4ilkmkk`.
Only a zero-byte uv lock remained. Process checks found no live owned process
before removing that lock/root. Three inaccessible pre-existing process
environments are recorded as an audit limit; readable command lines contained
no owned root. Caller-owned `.snektest/mariadb-data` remains untouched. No
stale-artifact sweep, global per-test environment mutation, or default exclusion
is introduced.

Typing, lint, formatting (634 files), generated interfaces and whitespace
checks passed:

```sh
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv run python scripts/generate_query_overloads.py --check
git diff --check
```

Actions is intentionally disabled. The host was not exclusive; no other suite
from this session ran during the full command. There is no remote matrix,
benchmark comparison or runtime-speedup claim.

Contract mapping, literal-oracle audit, commands, fault results and hashes are
in the paired JSON. Raw reports, owned source snapshots and scripts remain at
`/home/crpier/.cache/sq571-format-3i2BJ2Md`; the convenience pointer is
`/tmp/snekql-formatting-audit-latest`.
