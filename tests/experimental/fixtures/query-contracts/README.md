# Fixed supported deployment / historical-source refusal artifact

Actual archived writer/reader `6e6b0b18ac1e0b7e44b2f23e68d61d450090c661`
emitted `wide-old.json`, format2 digest
`7b96b56d9b2931965d62e1646ba29604c4a4d493721d514909bce8714f27e8ec`.
It records native VARCHAR(512) with logical `str` and the coarse TEXT storage hint.
The old source generator chose default `mariadb.Text()` (255-character policy): an
explicit original-model update compiled 300 characters, while the generated historical
model rejected the same value. This is lossy query-codec reconstruction, **not** a
migration false-completion artifact.

Current loading preserves the artifact's exact bytes/digest. Native deployment still
completes and an explicit query adapter updates/reads 300 characters. Only automatic
historical source generation refuses, requiring an explicit codec adapter. Do not
rewrite packages or receipts to make automatic generation succeed.

This checks a candidate default primitive against its recorded definition, not a
universal native-family-to-codec mapping. Physical migrations, logical query metadata,
Python validation hooks and durable codec provenance are separate contracts. Neither
old metadata nor successful deployment retrospectively certifies the original codec.
