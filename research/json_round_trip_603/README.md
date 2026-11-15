# Json[T], dump_python and the actual async drivers (#603)

2026-11-15. Bounded research in the existing redesign issue #603 / draft PR #609.
No new work queue, production implementation, default-flag adoption or merge.

## Question and confirmed public boundaries

The maintainer asked whether pydantic.Json[T] really fails with aiosqlite and
aiomysql when writes use dump_python. Test the public Pydantic validation/dump
methods and actual driver parameter binding/fetching, without a snekql converter.
Construction input is checked separately from driver compatibility. This is not a
replacement snekql API or a test of an imagined model/storage/query implementation.

## Result: it works with round_trip=True

```python
from pydantic import Json, TypeAdapter

adapter = TypeAdapter[dict[str, int]](Json[dict[str, int]])
value = adapter.validate_python('{"x":1}')

adapter.dump_python(value)  # {"x": 1}: a Python dict
adapter.dump_python(value, round_trip=True)  # '{"x":1}': JSON text
```

The second output binds unchanged through both tested drivers. It is still a
Python-mode dump, not a switch to dump_json or mode="json". Pydantic's explicit
Json annotation handles the encoded representation; storage does not select it.
No custom JSON serializer or snekql json.loads/json.dumps stage was needed.

The first output is not generally database-ready. In the dictionary case:

- aiosqlite raises ProgrammingError: type 'dict' is not supported.
- aiomysql raises TypeError: dict can not be used as parameter.

This does not claim every default-dumped JSON scalar fails. The dictionary is a
negative control demonstrating why dump_python without the flag is insufficient
as a general Json[T] write path.

## What was executed

[The harness](../../tests/experimental/test_json_driver_round_trip.py) has seven checks:

1. aiosqlite INSERT/fetch round trips, using SQLite TEXT with json_valid checking.
2. aiomysql INSERT/fetch round trips against a real private MariaDB server, using
   both JSON and LONGTEXT columns.
3. The ordinary dictionary dump really fails at aiosqlite binding.
4. The ordinary dictionary dump really fails at aiomysql binding.
5. Json[dict[str, int]] accepts encoded input and rejects a plain dictionary with
   json_type; an ordinary Pydantic model has the same input limitation.
6. Both BaseModel.model_dump and TypeAdapter.dump_python propagate round_trip=True
   to a Json field while keeping its validated field value a dictionary.
7. round_trip=True does not turn an ordinary dict annotation into JSON text.

Each driver's positive check covers object, array, string, integer, Boolean, JSON
null and nested/Unicode data, with independently specified expected Python values.
Raw returned values are strings and go directly into Pydantic validate_python.
JSON null is returned as the text "null", not SQL NULL. This does not establish a
single-field policy for preserving both JSON null and SQL NULL.

The initial SQLite round-trip test failed at actual binding without the flag;
changing only dump_python(value) to dump_python(value, round_trip=True) passed.
The same red/green sequence was then replayed against the real aiomysql connection.
Those initial failures are preserved under runs; trailing whitespace was normalized
for version control. The final harness keeps both failures as explicit negative
controls, so they remain reproducible despite the earlier logs' historical lines.

## Construction is a different question

Json[T] validates serialized JSON input and produces a logical T. For the object
case, supplying '{"x":1}' works; supplying {"x": 1} directly does not. The dump flag
does not change validation input grammar. That is not a failure to write the result
with either driver. It only matters if callers also want ordinary Python payloads
as validated construction input under the same declaration.

The previous discussion was too broad if read as saying Json[T] needs a custom
serializer to work with these drivers. It does not, in the tested round-trip path.
Whether the redesign should request round_trip=True by default is a subsequent
maintainer decision, not automatically adopted by this research.

## Reproduction and limits

```sh
uv run snektest tests/experimental/test_json_driver_round_trip.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The native checks require local MariaDB tools. They use the public temporary-server
helper only for lifecycle/setup, a private temporary directory and Unix socket,
then call aiomysql directly. Connections and the owned server close before the test
owner removes its directory. SQLite uses an in-memory database. No existing server,
application tables, retained fixture data, dependencies or driver configuration is
changed. Exact versions are in runs/environment.json.

This proves bounded Pydantic/driver interoperability, not snekql integration:
constructor/descriptor typing, annotation retention, per-field adapter selection,
comparison/update wiring, lifecycle handling, custom serializers/context and the
full supported backend/version matrix remain unproved. aiomysql was exercised
against MariaDB, not a separate MySQL server. No new tests at those unconfirmed
snekql seams, runtime rewrite or hidden compatibility converter are authorized.

## Preserved run records

- [Initial SQLite failure](runs/red-default-sqlite.txt)
- [Initial aiomysql failure](runs/red-default-aiomysql.txt)
- [Final focused result](runs/green.txt)
- [Environment](runs/environment.json)
