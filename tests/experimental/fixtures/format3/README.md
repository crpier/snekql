# Fixed format-3 composition chain

Exported from an isolated archive of writer
`7932c4fa07b0984f7bab99ed7c135de4503a22e4`. Its generator could not infer the
combined transition. The author explicitly supplied `RequireNotNull` followed by
`ChangeDefault`, cleared the unresolved decision, and froze them with that old
writer's compiler. The current generator now recognizes that composition.

- `001.json` (format 2): create SQLite `settings(id INTEGER PRIMARY KEY,
  value INTEGER)` with nullable/default-free `value`; digest
  `9b6fe83e9a0f4dac823c5d26b2001cdf36ba5d578838c730752b174da9b482c5`.
- `002.json` (format 3): require `value` and set DEFAULT 8 in one grouped rebuild;
  digest `0dd3db18f19647b3e10f08abd913f33999859273cd8c9123f76f51fab3d6ab52`.

The deployment test does not import the writer's models or regenerate these
files. It retains literal identities, an existing value, future insertion-default
behavior, predecessor linkage and completed history. Keep these bytes fixed;
future compiler changes must preserve compatible frozen execution or explicitly
refuse it, not regenerate historical artifacts or rewrite receipts. This is not
a general compiler/codec/ledger evolution or power-loss guarantee.
