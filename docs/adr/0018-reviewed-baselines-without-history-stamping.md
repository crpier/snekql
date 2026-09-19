# Reviewed baselines execute through ordinary migrations

An application adopting snekql can start its first canonical chain with a
hand-authored, reviewed baseline. The baseline creates the intended schema on
fresh replay and preserves matching existing objects during adoption. Both
paths execute the same migration body through `migrate()`. We do not add a
blanket stamp operation that records older migrations without executing them.

This preserves the sole schema-creation authority established in
[connect-only initialization](0007-imperative-migrations-connect-only-initialization.md).
[Partial model verification](0008-separate-partial-schema-verification.md) cannot
prove historical data transformations, CHECK constraints, triggers, or other
unmodeled effects. It therefore cannot justify stamping an arbitrary chain.
`IF NOT EXISTS` does not verify an existing object's definition either.

Adoption requires a backup, quiesced writers and deployers, reviewed catalog and
data evidence, and tests of both fresh replay and populated adoption. Preflight
checks run before migration; they do not hold a cross-step library lock. The
maintenance window must cover review, application, and post-verification.

Existing snekql history, including an empty history table, is outside this
one-time workflow. Use normal migration or explicit legacy-history adoption
instead. A deployed canonical chain must not be replaced with a baseline, and
baseline adoption must not manufacture its earlier entries. A database with
partially committed MariaDB DDL needs reconciliation, not history stamping.
