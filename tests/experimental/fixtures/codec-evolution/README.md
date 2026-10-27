# Genuine application-codec evolution (#477)

Engineering fixture, not consumer guide/new compiler or codec-ABI promise. Same account-role
transition on both backends, now with REAL replaced serializer/validator implementations.

`role_codec_v1.py.in` and v2 expose the SAME Role logical boolean via Annotated/Pydantic hooks.
V1 wire values: True→admin, False→user; v2: True→administrator, False→member. V2 rejects v1
text on decode. Model source, column names, storage/nullability and logical annotations do not
change; role_codec.py is overwritten at the SAME import path between separate consumer
processes, no mocks, monkeypatches, fake SQL formatting or hand-edited codec metadata.

Author001/002 with v1 codec. Opaque role query_type is None, automatic historical-source
reconstruction refuses; author uses its explicitly supplied v1 intermediate model instead.
Compare literal dumps with fixed archived704fd44-writer packages below. Replace codec with v2.
Re-authoring the SAME source with v2 yields different encoded bindings; old Package.check
rejects it as stale even though the recorded schema checkpoint digest is unchanged. Generating
against current v2 model produces no schema operations: opaque codec provenance was erased,
physical contract/digest is NOT a codec ABI or a codec-change detector.

Deploy COMMITTED old package bytes in a separate directory with no models/codec source;
author directory is deleted. Package.load/dump/digest remain identical, old bindings write
admin/user, old receipts complete and remain unchanged. Current v2 app separately verifies
structure but typed decode refuses; v2 True predicate encodes administrator and finds no v1
row. No silent reinterpretation/re-encoding or readiness certificate.

Author003 explicitly translates legacy physical strings through a query-only WireAccount
adapter. This adapter does not pretend to reconstruct the historical opaque codec. Model-
free deploy003, old receipts unchanged; current codec decodes logical booleans and new typed
insert writes administrator. No historical package/receipt edits, history deletion or replay.

The initial author-program RED incorrectly used v2 predicates for old values, updated no
matching rows and left the v2 app unreadable. This is an application data-migration bug, NOT
a claim that the library proves arbitrary data-change semantics. Correction was tested on a
FRESH isolated database, not by editing/replaying an applied003. A real already-applied bad
003 needs a separately reviewed follow-up revision/recovery decision, never receipt rewriting.

Actual archived704fd44 writer module paths printed in evidence. Fixed format2 role digests:
- SQLite: 26a9b626e3bc0b0c7e25f7d923e49c39f4585f0eec386cd2c1b0f0d77cc1fd4c
- MariaDB: 3bd1a4615c0f0248437c2d3030efbbb5d227cd4acc67700e4e1d80dc4ccd6baa
Never regenerate/convert historical references for a compiler change. Actual compiled bindings
are scalars, not serialized Python codec implementations or recoverable lost provenance.

Valid rendered programs are ty checked; child forced-lazy mode is propagated. Private native
server/caller exclusion, no unrelated database/global-setting changes. No production changes.
This is genuine APPLICATION CODEC evolution, NOT genuine framework compiler-emission/package-
format/ledger-layout evolution, cross-version codec reconstruction, arbitrary codec/data/
readiness/resource proof or native recovery claim. Those remain explicit work/scope decisions.
SQL trusted, guides deferred, incomplete/draft/not production-ready.
