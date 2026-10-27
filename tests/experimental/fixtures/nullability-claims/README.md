# Fixed ordinary-nullability refusal artifact

Actual archived writer/reader/runtime
`adb59a63cd66f6377af8c59248339fd482aa9bac` emitted and completed this format2
artifact, digest `c538bb8fa3a6961072c1bd6b21c8fa427a3bd37d3dc8a825dce961ef0a312d12`.
Its value ColumnState has nullable=False and an explicit NOT NULL definition, but
construction SQL omits NOT NULL. Real old SQLite execution marked it COMPLETE,
and insertion of NULL succeeded. Current loading/preparation explicitly refuses.

The valid companion is byte-identical to `../column-coverage/valid-old.json`,
digest `dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1`.
Keep bytes/identities fixed: no conversion, re-signing or receipt rewriting.
Ordinary nullability agreement is not primary-key nullability, general declaration
or expression equivalence, publisher authentication, or retrospective schema repair.
