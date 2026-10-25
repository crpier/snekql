# Recorded migrations: historical codec-evolution review (#477)

Status: experimental engineering assessment, not consumer guidance or a release decision.
This slice tests genuine application serializer/validator evolution, not cosmetic SQL changes
or an assertion that unchanged framework compilation constitutes compiler-epoch evolution.
No production interface, wire format, codec registry or ledger changes.

## What actually changes

`tests/experimental/test_migration_codec_evolution.py` runs isolated consumer programs for
SQLite and private MariaDB. Fixtures in `tests/experimental/fixtures/codec-evolution/` replace
role_codec.py at the SAME module path between processes. The role annotation remains the
same Annotated boolean/Pydantic hooks; column names/storage/nullability and model source stay
unchanged. Real serialization changes True from admin to administrator and False from user
to member. New decoding deliberately rejects old wire text. No mocks, declaration patches,
private helper assertions or edited package metadata make this distinction appear.

Actual archived704fd44 writer emits the fixed initial/role packages with v1 functions. Tests
compare literal author-generated dumps, then deploy COMMITTED bytes after v2 replacement and
removal of authoring sources. The migration process imports no model or codec implementation.
Frozen scalar bindings remain v1, body/digest/load unchanged, and real rows contain admin/user.
This confirms the relevant historical-execution guarantee without preserving importable v1 code.

## Four different checks, four different meanings

| Check | Observed result | Meaning |
| --- | --- | --- |
| Re-author same route under v2, then old Package.check(candidate) | refuses stale artifact | encoded bindings really changed; author/build freshness catches supplied changed route |
| Compare recorded checkpoint digests / generate against current model | digest unchanged / no schema operations | physical schema/query hint is not a custom-codec ABI or codec-change detector |
| Load and deploy old frozen package | succeeds, preserves admin/user bindings and receipts | historical executable scalar inputs are independent of today's application serializer |
| Current app verifies structure then fetches logical rows | structural verification passes; typed decoding refuses | migration/history/schema success is not application data/codec readiness |

The query_type field is None for the opaque annotated role. Old custom codec provenance was
not retained; it CANNOT be reconstructed or certified from storage family, bytes or the
unchanged digest. Automatic contract_source refuses and asks for an explicit codec adapter.
The v1 author supplies its historical intermediate model deliberately. This does not silently
upgrade generated-contract support or claim an old Python callback will remain available.

## Explicit transition to the new representation

A new003_codec revision is authored using a query-only physical-string WireAccount adapter:
legacy admin→administrator and user→member. This is explicit caller-owned knowledge of the
wire protocol, not inferred opaque provenance or an ownership change. The target schema is
unchanged and old001/002 bodies/digests/receipts remain unchanged. After model-free003 deploy,
the current v2 app decodes True/False and a typed new insert uses administrator. Repeating
frozen application reports already_applied, not a second data conversion.

The author-program RED used current-codec predicates against old data: they encoded v2
strings, matched no v1 rows and failed the final logical-data assertion. The corrected fixture
uses explicit old wire predicates on a FRESH isolated database. This is a meaningful data-
migration authoring error, NOT a newly found execution/compiler defect or an endorsed proof
of semantic success from UPDATE completion. In production an already-applied wrong003 must
not be edited/replayed or have history stamped/deleted; a follow-up revision or separately
reviewed recovery is required. Row/domain/application postconditions remain caller-owned.

## Product implications and remaining evolution work

- Frozen packages work across this real application codec replacement for already-encoded
  scalar data work. They do not need today's models or regenerate history from them.
- Author/build freshness must be integrated explicitly; deployment cannot know unprovided
  codec sources changed. Current generation does not infer a representation rewrite.
- Recorded physical/query hints do not preserve opaque codec identity/ABI. Choose finite
  supported historical typing scope versus an explicitly designed codec-provenance policy;
  never claim erased origins can be recovered or retrospectively certified.
- Genuine framework compiler-emission changes, old-epoch compiler selection or refusal,
  package-format evolution and ledger-layout/receipt evolution are STILL separate work.
  The archived writer here is real, but framework emission was not changed for this test.
- Realistic interruption/coordination and finite backend/version/release/ADR scope remain.
  Partial adoption/re-adoption limit from the ownership review is unchanged.

Evidence `.snektest/477-historical-evolution/` contains archived writer module paths, fixed
packages, actual per-backend programs/physical wire rows/current logical rows, changed-candidate
freshness refusal, structural-success/decode-refusal and explicit003 receipts. Normal/forced-
lazy consumers and real ty checks apply. No working-source mutation during native suites.
No generic SQL-equivalence, custom-codec ABI, whole-resource or blanket readiness guarantee;
SQL trusted, guides deferred, draft/incomplete/not production- or merge-ready.
