# Actual WAL role backfill interruption (#477)

`worker.py.in` is the model-free ORIGINAL Prepared executor, not an injected migration
step or driver adapter. Caller rendezvous is ONLY before apply. Normal/lazy flags propagate
and the worker reports actual mode. It imports no author/model/historical query modules.

The test authors/checks the existing visible role-interruption programs, compares all three
literal packages, removes authoring sources, installs this worker and durably saves ORIGINAL003
before execution. Same database path/endpoint throughout; no cross-target receipt comparison.
A real retained external SQL trigger audits row1's user-role UPDATE into65,536 actual512-byte
payload records. Its actual session synchronous value is part of each record. The trigger
survives the reviewed contraction; preservation does not adopt audit/workload tables.

A WAL reader pins the pre-transition snapshot. Controller observes real WAL growth, SIGSTOPs
only its owned client, confirms every thread stopped, validates physical header/frame checksums
and real uncommitted audit leaf records, then SIGKILLs/reaps it. No callbacks, UDFs, fabricated
responses/receipts, migration-step hooks, client rollback before kill or DELETE-journal proxy.

Fresh independent reads/public status see atomic rollback/no003 and all earlier own receipts;
SAME saved original completes once. Pinned WAL reader still sees old values despite the new
writer's successful COMMIT until it explicitly ends its snapshot. External sentinel/data/schema
and package/original bytes remain; ordinary typed app reads1admin2user and creates3user.

Normal/FULL are requested policies, not crash/power/host/fsync certification. Physical uncommitted
spill proves UPDATE-trigger work ran rather than BEGIN waiting; this is not selected COMMIT/DDL
ack loss or instruction-pointer tracing. Local WAL process-death qualification does not close
the maintained environment matrix or approve proposed ADR0023/release interfaces.
