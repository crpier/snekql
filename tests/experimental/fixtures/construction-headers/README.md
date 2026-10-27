# Fixed construction-header refusal artifact

`wrong-owner.json` is a format2 artifact emitted and accepted by actual archived
writer/reader `2b596f5d33fec13d823cddc41d8a055052786a34`, digest
`aaf90659f9b604bbf9ad6e81c05d02bc7aa6d1c13775b84af41fa3948b525c8c`.
It records/quotes the managed table name `entries` but executes ordinary CREATE TABLE
for `unowned`. Compilation/loading used to accept this; endpoint checks were later
responsible for refusal (with committed effects possible on native engines).

Current loading refuses the mismatched header before execution. The valid companion
is byte-identical to `../identifier-claims/valid.json`, digest
`d8bf43b6df3a741ec93fe3cd3df74b2fc906b15f14f5700aa08414a8d2f9e6a5`.
Keep bytes fixed: this is explicit reader tightening, not regeneration, conversion,
receipt rewriting, publisher authentication, or arbitrary SQL/claim equivalence.
