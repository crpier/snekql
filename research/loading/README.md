# Related-data loading and pagination

Research for #369. Same application operations on SQLite and MariaDB, with no
production fixes or imports from earlier research branches.

## Findings

Both libraries met the tested order-list and order-detail contract. The practical
tradeoff was explicit row assembly versus ORM loading policy, not correctness of
the final response.

snekql's projected joins and batched child read used two SELECTs for a nonempty
page. SQLAlchemy's select-in collection loader with joined scalar relationships
also used two. Its joined collection loader used one and correctly applied the
page limit to orders rather than joined rows.

That one-query result is not a performance verdict. The eager ORM plans loaded
children for the lookahead order as well as returned orders. The snekql plan trimmed
the parent page before loading children. Joined collection SQL also repeats parent
columns across child rows. We measured neither latency nor transferred bytes.

## Application contract

Approved entry points:

```python
await app.list_orders(customer_id, cursor, limit)
await app.get_order(order_id)
await observe(backend, strategy)
```

These are application functions, not HTTP handlers. Both implementations return
identical immutable dataclasses containing customer values, historical line items,
and integer-cent totals. No ORM objects or live iterators escape the functions.
The runner serializes every returned value after closing all database resources.

The list sorts by placed_seq DESC and id DESC. The integer placement key deliberately
avoids introducing another timestamp-codec comparison. Pagination uses an exclusive
two-field cursor and one extra parent to determine whether a next page exists.

The fixed specification for customer 1 is:

| Order | Placement key | Items | Total cents |
|---|---:|---:|---:|
| 102 | 30 | 1 | 125 |
| 101 | 30 | 3 | 880 |
| 103 | 20 | 0 | 0 |
| 104 | 10 | 5 | 150 |

Customer 2 has only order 201. Order 101 includes two separate lines referencing
the same product at different historical prices. Current product prices differ
from every historical price. The tests use these specification literals, not
values calculated from either implementation's output.

All eight backend/strategy configurations preserved the tied-key order, complete
collections, separate lines sharing a product, empty orders, customer filtering,
and exact totals. Following returned one-order cursors visited [102, 101, 103, 104]
without duplication or omission. A full final page correctly returned no next
cursor. Missing detail returned None, distinct from an empty existing order.

## Read plans and observed counts

Counts were identical on both backends:

| Plan | One returned order | Two returned orders | All four orders | Existing detail | Missing detail |
|---|---:|---:|---:|---:|---:|
| snekql projected join plus child batch | 2 | 2 | 2 | 2 | 1 |
| SQLAlchemy select-in collection | 2 | 2 | 2 | 2 | 1 |
| SQLAlchemy joined collection | 1 | 1 | 1 | 1 | 1 |
| SQLAlchemy per-order diagnostic | 2 | 3 | 5 | 2 | 1 |

No-parent pages required one SELECT in every plan. These counts apply to the small
fixture, not arbitrary select-in batch sizes or backend parameter limits.

### Explicit snekql reads

The first query projects order ID, placement key, customer ID, and customer name.
It joins the required customer and paginates only the parent rows. After trimming
the lookahead, a second query joins lines to products for the selected order IDs.

Application code groups those line tuples by order ID and initializes an empty
collection for every selected parent. That explicit initialization preserves empty
orders without needing nullable-side projection decoding. It sums historical
quantity times unit cents in Python. Neither read uses raw SQL.

The application selects only the response's required columns. The grouping map,
tuple unpacking, empty-parent handling, and DTO construction belong to the
application, not automatic relationship loading supplied by snekql.

### SQLAlchemy eager reads

The select-in plan uses joinedload for the scalar customer, selectinload for the
items collection, and joinedload for each item's product. SQLAlchemy assembles the
relationships; application code traverses them to construct the common DTO.

The joined plan changes the collection loader to joinedload. Its recorded SQL wraps
the limited parent query in a subquery before joining children. The application
calls unique() when consuming ORM results. Pagination therefore does not mistake
three child rows for three orders or truncate the second order's collection.

Both plans use raiseload("*") for relationships not covered by the declared loading
options. This is added application discipline, not an untouched ORM default.
Each operation creates a new AsyncSession, so a warm identity map cannot conceal
missing reads. DTO conversion occurs before transaction exit; the application does
not depend on retained ORM attributes surviving commit or session closure.

### The lookahead difference

For a one-order page, the first query reads orders 102 and 101. Only 102 is returned.
The recorded snekql child query has one ID parameter. The SQLAlchemy select-in
query has both 102 and 101, including the three lines belonging to the unreturned
lookahead order. Joined eager loading includes that order's children in its single
query too.

This follows from the implemented plans. It is not an unavoidable SQLAlchemy
limitation. An application could first select the parent page, trim it, and then
load the selected graph. Conversely, snekql could load lookahead children before
trimming. Query count alone hides this choice.

The ORM plans also load mapped columns absent from the response, including current
product prices. We did not add load_only tuning or compare every equivalent plan.
That observed difference is between these implementations, not a claim that an ORM
cannot project narrowly.

### Per-order diagnostic

The diagnostic explicitly awaits each selected order's collection through
AsyncAttrs. Its customer and product relations still use joins. This is a valid
async N+1 pattern, not an accidental synchronous lazy load that fails before it can
produce a response.

It returns the correct result but grows from two SELECTs for one order to five for
four. It is not the representative SQLAlchemy implementation. An explicit snekql
loop could make the same mistake; the batching benefit belongs to the read plan.

## Ergonomic observations

SQLAlchemy removed manual grouping of child rows and preserved an object graph for
application traversal. Correct use still involved choosing loader paths, accounting
for joined-result deduplication, controlling accidental loading, and copying values
before session ownership ended.

snekql made selected columns and the two query boundaries explicit. The application
owned more of the assembly. Both backend implementations use concrete typed models
and projections rather than an Any-based query adapter. They are separate files
with the same algorithm so ty checks each backend's public query types directly.

Both applications return the same typed DTOs. The narrow typing exception covers
SQLAlchemy's Any-parameterized declaration factories in its model file only. This
exercise checks the written code; it is not a general typing-soundness evaluation
or a usability study based on developer effort or declaration length.

## Evidence and reproduction

There are eight configurations, 128 recorded application reads, and 155 research
checks. The complete package plus research suite passed 1764 tests. Typing, Ruff,
formatting, and lock validation passed. A clean temporary environment also passed
the 155 research checks and typing after installing the comparator requirements.

```sh
export PYTHON_CONTEXT_AWARE_WARNINGS=1
uv sync --locked --all-extras
uv pip install --python .venv/bin/python --requirements research/loading/requirements.txt
uv run python -m research.loading.experiment
uv run snektest tests research/loading
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

Requires local mariadbd, mariadb-install-db, and mariadb binaries. The runner owns
its temporary files and socket-only servers, including deletion after shutdown.
It accepts no external connection URL. The comparator requirements are pinned
separately; root dependencies and uv.lock are unchanged.

Recorded versions: Python 3.14.2, SQLite 3.50.4, MariaDB 12.3.2, SQLAlchemy 2.0.43,
greenlet 3.5.1, Pydantic 2.13.5, aiosqlite 0.22.1, aiomysql 0.3.2, and PyMySQL 1.2.0.
The snekql checkout reports 0.7.0 but uses main base 50b7a9a, not the published 0.7.0
artifact. Database binaries are observed rather than installed by the runner.

SQLite uses WAL and foreign keys. The SQLAlchemy connection policy explicitly
issues BEGIN, so its multi-query reads do not rely on legacy SELECT behavior.
MariaDB controls report InnoDB, REPEATABLE READ, snapshot isolation enabled, UTC,
strict SQL mode, and foreign keys. No concurrent writers run during this study.
Installed storage declarations remain idiomatic, including SQLite STRICT for
snekql and differing integer widths on MariaDB. The fixed valid inputs fit both.

Start review with SPEC.md, then sqlite_app.py or mariadb_app.py and sqlalchemy_app.py.
resources.py owns setup and teardown. experiment.py records results and query traces.
results.json contains all outcomes, controls, installed DDL, and completed SELECTs;
the eight .sql files separately retain table DDL.

snekql query evidence comes from its runtime DEBUG completion records, not calls to
the compiler. SQLAlchemy evidence comes from after_cursor_execute. Setup, schema
inspection, BEGIN, and COMMIT are outside the counts. snekql parameters remain
redacted; ORM traces show the fixed fixture parameters. These observers describe
sequential successful reads, not a production concurrent tracing integration.

Limits: positive valid page limits, static data between requests, valid foreign
keys, one small graph, and one installed version combination. No authorization
claim for get_order, orphaned-row behavior, large-batch thresholds, concurrent
pagination guarantees, memory profiling, or latency ranking. The code is research,
not a proposed production repository layer.
