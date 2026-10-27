# Fixed native ON UPDATE construction artifacts

Actual archived692e316 writer/reader/runtime emitted/loaded/prepared real format2:
metadata DATETIME(6) NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP(6), construction
without ON UPDATE. DDL committed, then UNCERTAIN/AMBIGUOUS; NOT false completion.
Current literal load/typed prepare refuse before schema/history effects.

| Artifact | Digest |
| --- | --- |
| invalid-old.json | 46855019e64fbd2d9b59e88cf381a4083943e8a7777e7a44bb5e55940ae0b83f |
| valid-old.json | 1141d4e610f1421b0174b40ed85878eac09651e79222852ad7511f5652f093de |

Truthful companion retains literal dump/digest/model-free deployment. Deterministic session
clock writes demonstrate NULL default, unrelated-change clock update and explicit unchanged
column suppression separately. No conversion/digest/ledger/receipt rewriting, retrospective
repair/certification, exact clock/timezone/future-session/data/readiness or recovery shortcut.
SQL trusted/unsandboxed. FK ON UPDATE/SET NULL actions are separate bounded roles, not
automatic timestamp updates or ordinary nullability. No full FK compatibility certificate.
