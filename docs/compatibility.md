# Compatibility and the 1.0 release contract

snekql is still on **0.x**. A minor release can change existing code, so pin the
minor version and read the [changelog](../CHANGELOG.md) before upgrading. Breaking
changes must include migration instructions.

The guarantees below are the plan for **1.0 and later**, not a claim that 1.0 has
shipped. They explain which changes will require a major release, how deprecations
will work, and what must pass before release.

## Public APIs

The supported imports are the exports in `snekql.sqlite.__all__` and
`snekql.mariadb.__all__`, plus those two namespaces from `snekql`. Their documented
classes, methods, properties, factories and annotation aliases are public.
Documented exports from `snekql.telemetry`, `snekql.opentelemetry` and
`snekql.testing.mariadb` are also public. The optional OpenTelemetry adapter does
not make OpenTelemetry a mandatory dependency.

A symbol's definition module does not create another supported import path.
Private modules, backend implementation submodules, generated overload machinery,
Execution Plans, private class attributes and undocumented subclassing hooks are
not public APIs. The source-checkout benchmark and development scripts are not
installed application APIs. Documented `snekql` and `snekql-mariadb-server` CLI
commands, options and exit-code meanings are public; help layout and prose are
not a machine-readable protocol.

### Experimental recorded packages are a separate contract

The opt-in [recorded workflow](recorded-migrations.md) stays in
`snekql.experimental.migrations`. Its finite engineering acceptance is neither a
stable namespace move nor an indefinite ABI promise for every exposed prototype
value. The 1.x raw-history promise below does not automatically apply to its
experimental ledger. Supported frozen formats/interpretations are read as defined
or refused; there is no implicit conversion of unsupported ledgers, prepared
plans, timestamps, codecs, or data. Retain original artifacts and evidence before
upgrading; do not regenerate them to fit a new reader.

The released raw-SQL runner remains supported unchanged, with no selected
removal/deprecation. Keep the two runner families on separate deployment targets;
there is no automatic raw-to-recorded history conversion, chain replacement,
stamping, or cutover. Current application mapping and readiness are independent
of either chain's ownership or completion. Consult the recorded guide's exact
positive builds and exclusions rather than treating the ordinary backend matrix
as a wider recorded-migration certificate.

### What stays compatible within 1.x

| Area | Promise |
| --- | --- |
| Imports and calls | Keep public import paths, callable signatures, documented defaults and supported keyword arguments. Adding an optional operation must preserve existing calls. |
| Typing | Preserve documented inference, annotation arity, result shapes, backend identity and Pending/Row distinctions under the supported checker profile. An accepted, valid helper must not require a new cast, ignore or annotation merely to upgrade snekql. |
| Query behavior | Preserve explicit Query Readiness, result cardinality, nullable joined rows, validation ownership and ordered positional or named result shapes. `fetch_one` remains exactly-one, not optional-one. |
| SQL semantics | Preserve the meaning of supported expressions, parameter binding, NULL handling, conflict behavior and dialect-specific restrictions. Neither backend is a transparent substitute for the other. |
| Transactions | Preserve explicit transaction boundaries, task ownership, cancellation cleanup, separate acquisition and operation deadlines, and truthful Commit Outcome evidence. Never replay an uncertain commit implicitly. |
| Schema declarations | Preserve supported declaration syntax, fixed declaration facts, storage/logical-type meaning and codecs' documented wire forms. Models do not create or alter tables at initialization. |
| Migration history | Preserve ordered identities and exact-body checksums. Existing canonical history must remain readable, or a major upgrade must provide an explicit conversion procedure. No silent history rewriting or stamping. |
| Verification | Preserve documented matched, drift and unchecked meanings and strict/warn behavior. Partial verification does not become a claim of complete schema equality. |
| Errors | Preserve public exception classes, catchable hierarchy and documented structured attributes. All intentional package-originated failures remain `SnekqlError` subclasses. Cancellation and arbitrary user-code failures are not rewritten into that hierarchy. |
| Diagnostics | Preserve default parameter redaction and explicit opt-in value inspection. Preserve documented telemetry field meanings and bounded optional-adapter behavior. |

Generated SQL whitespace, aliases, placeholder names, query plans, exception
messages, repr/str layout and log prose may change. `.compile()` still returns
valid SQL and correctly ordered or named parameters for its backend. Applications
must not parse repr or exception text instead of the structured APIs. No fixed
latency, throughput or native-memory ceiling is promised.

Compatibility does not freeze database-server behavior, collation definitions,
query planner choices or undocumented driver behavior. A dependency upgrade must
still pass the supported runtime and typing contracts before release. Raising a
supported Python or database minimum within 1.x is a breaking change, not a
routine dependency refresh. Python 3.15+ and SQLite/MariaDB remain the scope;
MySQL, PostgreSQL and ORM behavior are not implied by 1.0.

## Version and deprecation rules

After 1.0, patch releases fix defects without intentionally changing supported
behavior. Minor releases add compatible capabilities and may announce
deprecations. Breaking changes require a major release, including typing-only
breaks. Loss of tuple inference, added optionality, changed public generic arity,
new required annotations or stricter rejection of previously valid programs all
count even when runtime tests still pass. A supported checker-version change
must include consumer conformance results and any application migration steps.

An additive change is not automatically compatible. Adding a required field,
changing a default, widening a documented closed set of outcomes, or enabling new
strict verification that rejects previously conforming startup needs the same
compatibility review. Offer an opt-in first or reserve the change for a major
release.

For an ordinary removal or incompatible replacement:

1. Ship a usable replacement in a stable minor release. Record the deprecated API,
   reason, replacement, first notice version/date and earliest removal conditions.
2. Keep the old contract for at least **180 days and two subsequent minor
   releases**, whichever takes longer. A deprecation first announced in 1.2 must
   remain through 1.3 and 1.4. Removal still requires 2.0 or a later major release.
   Prereleases do not satisfy either minor-release requirement.
3. Add a runtime `DeprecationWarning` where the call can be identified without
   changing its behavior. For typing-only APIs or cases without a safe runtime
   warning site, put the notice in the typing guide and changelog instead.
4. Before removal, publish an upgrade guide with before/after imports and calls,
   inferred and annotated types, changed defaults/errors, database prerequisites,
   data or migration steps, deployment ordering and rollback limits. Say explicitly
   when rollback cannot safely undo database changes.

Fixing rejection of an input already forbidden by the documented contract is a
bug fix. Rejecting a previously documented valid program is not. Do not label an
inconvenient typing regression a bug fix to bypass the notice period.

A narrowly scoped security or data-corruption fix may bypass the normal notice
period when retaining the old behavior is unsafe. Release notes must identify the
exception, affected versions, user action and why a compatible remedy was not
safe. Publish a security advisory when appropriate. This exception is not a
route for routine cleanup or feature redesign.

## Security and backports

The maintenance window is deliberately one released minor line. Security fixes
and ordinary patches go to the **latest stable minor of the latest stable major**.
When a new stable minor or major ships, older lines stop receiving fixes.
Prereleases do not displace the stable line. There is no overlapping backport
window, LTS branch, paid response SLA or guaranteed fix deadline.

This keeps the existing latest-minor policy rather than promising parallel
maintenance the project cannot staff. Deprecation support means keeping the old
API usable in current releases during its notice period; it does not mean
patching every old distribution for 180 days. Consumers who need supported fixes
must budget for minor upgrades and, when required, major upgrades. Pin exact
versions for reproducibility, but schedule updates rather than treating a pin as
an extended-support contract.

Use the private reporting process in [SECURITY.md](../SECURITY.md). An old-version
report is still welcome, but a fix may require upgrading to the supported line.
Report acknowledgment is a best-effort target, not a guaranteed repair date.

## Measurable 1.0 release gates

The release PR must attach evidence for its exact candidate commit. An issue
being closed, an old green run or a PR waiting to merge is not enough. Re-run
affected checks after candidate changes and record any reused evidence and why
its inputs are unchanged.

| Workstream | Required evidence |
| --- | --- |
| [Typed SQL, #274](https://github.com/crpier/snekql/issues/274) | Positive and intentional-negative typing contracts, generated-interface check, both-backend query semantics and documented unsupported constructs pass. |
| [Transactions, #281](https://github.com/crpier/snekql/issues/281) | Native tests pass for explicit transactions, savepoints, deadlines, cleanup, settings restoration, TLS and uncertain commits. No unexplained failure or skipped required environment. |
| [Schema evolution, #287](https://github.com/crpier/snekql/issues/287) | Fresh replay and populated adoption pass; drift/unchecked reporting, rolling-history rules and reviewed-baseline safeguards retain their tests. |
| [Production evidence, #292](https://github.com/crpier/snekql/issues/292) | Telemetry/redaction tests and the failure/environment inventory pass. A dated raw-driver/snekql/SQLAlchemy Core comparison covers both backends with validated outputs, repeated trials and recorded environment. Re-run affected workloads after runtime changes; there is no throughput ranking gate. |
| [Adoption contract, #297](https://github.com/crpier/snekql/issues/297) | The selected maintained MariaDB matrix passes native suites; exact checker versions and limitations are published; this policy and the adoption/API/service guides are complete. Required child PRs must be merged. |

The release checklist in [adoption.md](adoption.md#release-checklist) supplies the
commands. Required checks include the full snektest suite, ty, Ruff lint/format,
lock consistency, generated interfaces, clean wheel/sdist builds and isolated
artifact smoke tests. When CI is enabled, required jobs must pass on the candidate, including SQLite
OS/version coverage, selected native MariaDB versions and security checks. While
Actions are maintainer-disabled, use completed local reports for the explicitly
selected scope; do not request/poll Actions or describe unrun jobs as passing.
Each exclusion needs an explicit release-blocking decision, not a green claim
based on an unrun check. Publish known limits with their reproduction evidence.

1.0 does not require every SQL feature. Raw SQL remains an explicit escape hatch
with a declared consumption contract. Recursive CTE builders, window builders,
set-operation builders, every index form, extra database families, automatic
migrations, identity maps and lazy relationships are not release gates. A feature
enters the gate when its absence breaks an already promised contract, not merely
because another library offers it.

### Release authority and artifact provenance

Follow the repository's current maintainer-controlled release process in
[the release checklist](adoption.md#release-checklist). Open a release PR, retain
exact candidate/artifact identities and validation reports, and wait for explicit
merge/publication authority. The human maintainer runs `uv publish`; documentation
or local packaging work does not authorize that step, a version, a tag, or merge.
Do not publish a GitHub release as a harmless announcement: the retained
[release workflow](../.github/workflows/release.yml) can publish when enabled.
Never reuse a release tag or publish the same version by both manual and automated
paths.

Actions are currently maintainer-disabled. Do not infer a build attestation,
Trusted Publishing approval, or PyPI attestation from a local artifact build or a
workflow file. If a future release explicitly restores the automated path,
separately verify tag/version equality, environment approval rules, Trusted
Publisher configuration, and provenance for the exact distributed artifacts.
A workflow environment name alone does not prove human approval. After authorized
publication, run the published-package smoke outside the checkout.

[All guides](README.md)
