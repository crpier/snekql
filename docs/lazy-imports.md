# Python 3.15 and lazy imports

snekql requires **Python 3.15+** and **Pydantic 2.14+**. For uv-managed Python,
use **uv 0.13.0 or newer**: older uv download catalogs may only offer release
candidates. The checkout pins Python 3.15.0; package metadata permits later
versions.

All runtime import statements in `snekql/` use Python 3.15's explicit `lazy`
syntax. Python loads each imported dependency on first use of its binding.
Imports used immediately by decorators, class bases, or module initialization
still resolve immediately; this is not a promise that every dependency remains
unloaded after accessing a backend namespace.

Importing the package root alone does not initialize either backend. Documentation
CLI help also avoids loading the backend namespaces. Import-time backend
registration is explicitly triggered when a namespace initializes, so query
compilation and the default SQLite database initializer retain their behavior.
Optional drivers remain optional; a missing SQLite extra still reports the
`snekql[aiosqlite]` installation hint when initialization is attempted.

The library uses native deferred annotations, rather than
`from __future__ import annotations`. Native annotation evaluation resolves lazy
bindings when runtime validation needs them. Caller models may still use the
future directive; existing model annotation regressions cover both forms.
Static `.pyi` interfaces are not runtime imports and retain ordinary syntax.

## Forced-lazy validation

Python's actual global flag is `-X lazy_imports=all`, not a boolean switch:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  -m snektest tests/packaging
uv run python -X lazy_imports=all -m snekql --help
```

The packaging regressions run without an import filter and include fresh-process
query compilation for both backends and invalid-config rejection. Built-wheel
smoke checks also exercise the flag without a filter.

The complete suite includes Hypothesis, whose strategy decorators and export
checks rely on eager internal imports. Hypothesis 6.168.1 and the tested latest
patch, 6.168.5, fail their own export assertions under unfiltered forced-lazy
execution. OpenTelemetry SDK 1.45.0 and the tested latest patch, 1.45.1, also
have a metrics dataclass/export import cycle under the global flag.
The complete-suite runner works around these **only in test tooling**:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests
```

Its filter disables laziness only for imports *executed inside Hypothesis or
OpenTelemetry SDK*. It does not exempt snekql, tests, standard-library modules,
OpenTelemetry API, or other dependencies.
The runner does not disable global lazy mode or install any library monkey patch.
The flag applies to the test process; separately launched subprocesses are not
implicitly forced-lazy, which is why fresh-process and wheel regressions pass
that flag explicitly.

Python itself forbids explicit lazy imports inside functions, classes,
`try` blocks, future directives, and star imports. The library's former local
imports have moved to module-scope lazy bindings. Runtime `import_module()`
calls remain deliberate eager loading at explicit runtime/CLI boundaries.

See [the migration review](dependency-reviews/2026-10-09-python315.md) for exact
versions, validation results, and untested environments.

[All guides](README.md)
