# Type-checker compatibility

**ty 0.0.77 remains the primary checker.** It checks the repository, examples and
intentional-negative typing contracts. This assessment does not reverse that
choice or weaken library annotations to accommodate another checker.

## Tested versions and scope

Assessment dated 2026-09-20, clean source revision
`08ccf6b08754e1bbbeb9cf2297effe473f0f6888`, CPython 3.14.2, Linux x86-64.
All tools target Python 3.14 and resolve dependencies through the same project
interpreter. The reports record dependency versions, OS, exact arguments and
SHA-256 hashes of the rendered positive/negative source files.

| Tool | Version | Decision |
| --- | --- | --- |
| ty | 0.0.77 | Primary supported checker; full repository validation plus 14/14 consumer pairs |
| Pyright CLI | 1.1.414 | Supported for the consumer profile below, in strict mode; 14/14 pairs |
| mypy | 2.3.1 | Not supported for the complete query typing contract; 10/14 pairs |
| Pylance | Not assessed | Editor integration and bundled engine version are not certified by the Pyright CLI result |

Python 3.14+ remains intentional. These observations do not certify older Python,
other checker versions, another OS, every API combination or a complete Pyright
check of the library's internal implementation. Consumers should upgrade tools
through the same probes rather than assume every newer release is equivalent.

The consumer profile uses only supported `snekql.sqlite` and `snekql.mariadb`
namespace APIs. It checks inference, public helper annotations and intentional
invalid operations. A passing negative requires a clean matching positive
control and at least one error at the marked invalid operation. Unrelated errors
and errors in a broken positive control cannot earn a passing result.

| Contract, checked on both backends | ty | Pyright | mypy |
| --- | --- | --- | --- |
| Pending/fetched states and generated IDs | Pass | Pass | Pass |
| Executable select readiness | Pass | Pass | Pass |
| Backend identity at Transaction execution | Pass | Pass | Pass |
| Eight inferred positional slots; ninth rejected | Pass | Pass | Fails valid control |
| Nine-field named result inference and helper boundary | Pass | Pass | Pass |
| Left-join optional right model | Pass | Pass | Fails valid control |
| Raw construction owns validation and result shape | Pass | Pass | Pass |

These are seven focused contracts, not an exhaustive claim about every method.
Runtime checks still own dynamic inputs, declaration consistency, named binding
labels, SQL scope and value validation. A checker cannot prove those properties
for arbitrary Python programs.

### mypy limitations

On valid eight-column projections, mypy 2.3.1 infers `Never` for some owner/value
parameters, requests an annotation for the query, and loses the fetched tuple
slots to `Any`. On valid left joins it reports descriptor-owner and overload
mismatches and loses the inferred result to `list[Any]`.

The negative examples also contain those positive-control errors, so their
additional rejection does not establish compatibility. The reports retain all
diagnostics. No casts, `Any` substitutions, weakened overloads or checker-specific
ignores were added to make these cases appear supported. Passing the other five
contracts is useful evidence, not a general mypy support promise.

## Reproduce the assessment

From a source checkout with the locked development environment:

```sh
uv sync --locked --all-extras
uv run python scripts/check_typing_compatibility.py > ty-report.json
uv run python scripts/check_typing_compatibility.py --checker pyright > pyright-report.json
uv run python scripts/check_typing_compatibility.py --checker mypy > mypy-report.json
```

The mypy command currently exits **1** because the report records incompatibility.
Exit 0 means every selected pair conforms. Exit 2 means the assessment could not
run reliably, such as missing tools/input files, malformed diagnostics or a
90-second deadline. Never treat exit 2 as a successful compatibility observation.

`--backend sqlite|mariadb` and `--case <name>` select a narrower assessment;
defaults cover all seven cases on both backends. The CLI does not execute the
consumer programs or connect to a database. Templates live under
[`typing_probes/`](../typing_probes/), with `.py.txt` suffixes so ordinary project
checks do not accidentally treat intentional-invalid examples as library errors.

Secondary tools run through version-pinned `uv tool run` environments, not new
runtime dependencies. They need uv and either network access or populated tool
caches. Pyright also needs Node.js, directly or through its wrapper's provisioning.
The recorded local assessment used Node.js 25.2.1. Each secondary checker receives
an explicit strict configuration; ty uses the repository's all-errors policy
with the existing missing-override-decorator exception. Ambient `TY_CONFIG_FILE`
cannot replace the declared assessment configuration.

Raw dated reports:

- [ty](../typing_probes/results/2026-09-20/ty.json)
- [Pyright](../typing_probes/results/2026-09-20/pyright.json)
- [mypy](../typing_probes/results/2026-09-20/mypy.json)

Temporary paths in the recorded underlying arguments identify that execution's
inputs; they are removed after the run. Reproduce through the CLI, which renders
new copies from the checked-in templates. Source hashes identify those contents.
A dirty checkout is reported as dirty; it is not presented as a clean revision.

## Editor guidance

Select the application's Python 3.14+ environment, including its installed
snekql and Pydantic dependencies. Keep `uv run ty check` as the project gate.
Use ty's editor integration when you want diagnostics aligned with that gate.

For a Pyright CLI consumer project, start with an explicit configuration:

```json
{
  "pythonVersion": "3.14",
  "typeCheckingMode": "strict",
  "venvPath": ".",
  "venv": ".venv",
  "include": ["src"]
}
```

Adjust paths to the application. Pin the assessed CLI version. This does not
configure or pin Pylance's bundled engine. Pylance completion may still be useful,
but its editor diagnostics need separate evaluation. When an editor disagrees,
first reproduce with the pinned CLI and correct interpreter; do not silence a ty
failure merely to satisfy an unassessed editor. Pylance, PyCharm and other editor
engines have no additional conformance guarantee from this assessment.
