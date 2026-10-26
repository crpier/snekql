# Column-default design review sheet — #473

Agreed with the maintainer, 2026-10-26. No design is selected.

## Shortlist

1. Separate `default` (Python) and `server_default` (SQL).
2. `default_on="python"` / `default_on="server"` selector.
3. Prefixed server constructors, previously called `ServerInteger`/`ServerText`.

Names remain provisional. The annotation-left / SQL-right split and its typing
generator are abandoned. Symmetric policy wrappers are a research challenger,
not a fourth maintainer-approved shortlist item. The outer wrapper remains
lower-ranked for verbosity; a server namespace ranks below prefixes.

## Core scenarios

| ID | Scenario | Omitted Python argument | SQL declaration |
| --- | --- | --- | --- |
| R1 | Required non-nullable | Rejected | NOT NULL, no default |
| R2 | Required nullable | Rejected; explicit None accepted | Allows NULL, no default |
| R3 | Python value default | Concrete value | NOT NULL, no default |
| R4 | Python None default | None | Allows NULL, no default |
| R5 | Nullable Python value default | Non-None value; explicit None accepted | Allows NULL, no default |
| R6 | Python factory | Factory result | NOT NULL, no default |
| R7 | Server literal default | Pending sentinel | NOT NULL, literal SQL DEFAULT |
| R8 | Server expression default | Pending sentinel | NOT NULL, SQL expression DEFAULT |
| R9 | Nullable server default | Pending sentinel; explicit None accepted | Allows NULL, non-NULL default |
| R10 | Server NULL default | Pending sentinel; explicit None accepted | Allows NULL, DEFAULT NULL |
| R11 | Server identity | Pending sentinel; explicit ID accepted where supported | Identity/auto-increment, not SQL DEFAULT |

A nullable server default is meaningful: an expiration could default on omission
but accept explicit NULL for "never expires". NULL is not a request to use the
SQL default.

## Contrast cases, not shortlist admission gates

- C1: required Python input despite a SQL default (for example, for other writers).
- C2: concrete Python default and SQL default together, if natural in the design.
- C3: required `GenCol` input: explicit value or explicit pending sentinel, but
  omission rejected. Generated state does not itself imply constructor omission.

Do not add machinery just to permit or prohibit coexistence. Record limitations.
"No concrete Python default" and "required Python argument" are not synonyms.

## Evidence each design must present

For each core scenario, show:

1. Declaration.
2. Constructor omission: rejection, value, factory result, or pending sentinel.
3. Explicit value and explicit None acceptance/rejection.
4. Pending field's exact static type and intended actual initial value.
5. Intended INSERT supplied/omitted column and SQL schema/nullability/default.
6. Completed Row's exact type.

Also show nonsense and near-misses, distinguishing:

- Rejected by syntax/signatures/type checker, with independent clean controls.
- Accepted by ty but requiring runtime declaration validation.
- Valid but surprising (for example, SQL default with required Python input).
- Unsupported by this prototype, rather than impossible in the design family.

Audit wrong default types, wrong factories, incompatible NULL, wrong Col/GenCol
states, pending markers without declared generation, missing generation sources,
selector mistakes, contradictory modes and identity settings. Constructor input
precision alone does not prove declaration validation.

## Research boundary

Only the agreed declaration and consumer-typing seams are exercised. Never
execute model templates, factories, INSERTs or databases. SQL, initial values,
factory timing, omission and verification behavior above are intended contracts,
not runtime-tested facts. Native ty 0.0.84 is the supported checker. No generated
typing evidence, dependency changes, production changes or breaking migration
policy are authorized. Validate locally; do not wait for GitHub Actions.
