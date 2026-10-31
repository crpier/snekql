# Zero-wrapper `Unparsed[T]` and direct Pydantic validation

Executed attribute-level proof for issue #593, requested by the maintainer after
source-only draft #594. Research only: **not a proposed or adopted snekql public
interface**. Baseline: `a1cf31d8dba78f9ddf0a2b687f5c188649c14391`.

## What this proves

[The standalone source](proof.py.txt) defines an opaque generic marker class but
**never instantiates it**. `typing.cast` marks the driver's `object` as
`Unparsed[int]` without wrapping, parsing or replacing the value. This is an
explicit trust operation at the producer, not evidence of the logical type.
The additional casts to `object` model the unknown input type a driver would
supply; ty would otherwise retain the known literal types in this small example.

Direct `TypeAdapter(int).validate_python(raw_value)` then returns `int`, without
an unwrapping hook, helper parsing function or cast of the parsed output.

The [tests](../../tests/research/test_unparsed_type_adapter.py) verify:

1. **Runtime identity and parsing**: the marked integer remains the original
   integer, and the marked string remains the original string. Both are validated
   directly, with the string parsed into integer 42.
2. **Native static checking**: exact `assert_type` controls pass for both
   `Unparsed[int]` inputs and `int` outputs. Three appended assignments are
   rejected, with exactly one `invalid-assignment` on each expected line:

   ```python
   needs_parsing: int = raw_age
   wrong_contract: Unparsed[str] = raw_age
   wrong_output: str = parsed_age
   ```

The unchecked input's `T` remains meaningful and is distinct from both an
ordinary `T` and another unchecked contract. The proof uses no `Any` annotations,
checker patches, suppression comments, runtime wrapper instances or snekql
imports. Pydantic itself accepts arbitrary validation input; its input annotation
is not narrowed to `Unparsed[T]`.

## Run it

```sh
uv run snektest tests/research/test_unparsed_type_adapter.py

# Inspect/runtime-check the standalone example separately:
cp research/unparsed_593/proof.py.txt /tmp/snekql-unparsed-proof.py
uv run python /tmp/snekql-unparsed-proof.py
uv run ty check /tmp/snekql-unparsed-proof.py
```

The runtime example prints:

```text
True int 42 int
True str 42 int
```

Each row reports unchanged input identity, input runtime type, parsed output and
output runtime type. Static `assert_type` calls are checked by ty, not asserted
at runtime. The invalid assignments are checked separately, never executed.

## Limits

- **The adapter determines the output type**, not the input marker. Pydantic's
  validation method does not enforce that `Unparsed[T]` matches its target `T`.
  Callers must select the intended contract; the marker does not reify an adapter.
- Constructing `TypeAdapter(int)` is sufficient for this example, not a general
  substitute for retaining an attribute's actual constraints/`Annotated` metadata.
- The marker class exists at runtime, but no value is made an instance of it.
  Runtime `isinstance(value, Unparsed)` or schema inspection of the marker itself
  would not describe the real input. It is solely static provenance in this proof.
- No whole-model field transformation, JSON contract, backend representation,
  query result typing, streaming, RETURNING or three-mode integration is proved.
  JSON text would need its appropriate JSON contract rather than plain Python
  validation of `list[T]`.

## Red/green and validation

The runtime test first failed because the proof source did not exist. The first
candidate used transparent `type Unparsed[T] = T`: runtime and positive static
controls passed, but the negative test correctly failed because unchecked-to-`int`
assignment was accepted. Replacing only that alias with the never-instantiated
marker class made both tests pass. An earlier static control also exposed ty's
literal narrowing/disjoint-cast check; explicit `object` inputs resolved it without
suppressions. These are isolated proof changes, not production implementation.

Executed environment: Python 3.15.0, Pydantic 2.14.0, pydantic-core 2.50.0,
ty 0.0.84 and snektest 0.16.0. The two focused tests passed. Project-wide ty,
Ruff lint/format, explicit lint/format of the standalone source and diff checks
also passed. The standalone source's explicit lint excludes package-only `INP001`;
its cast spelling and the test's formatting were fixed before final checks.
No full suite, database operation, benchmark, dependency change or
production change was performed. No merge or issue closure is requested.
