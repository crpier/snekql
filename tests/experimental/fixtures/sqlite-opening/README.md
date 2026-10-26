# Real SQLite physical opening

`lease.py.in` owns one Linux write lease on the supplied file. SIGIO reports an actual open
attempt; stdin release/EOF ends the lease. It changes no global settings or unrelated files.
It is an OS helper, not a SQLite/driver implementation.

`operator.py.in` is the visible public consumer: deadline/task/scope interruption of `m.connect`,
actual kernel worker-TID/database-FD disposal, then explicit fresh acquisition and committed
role001/002/003 deployment with ordinary initial/current typed models. It reloads ORIGINAL
Prepared bytes, checks complete/already_applied, and reads1admin/2user/3user. ResourceWarnings
are enabled by the controller to distinguish explicit close from implicit GC cleanup.

The controller asserts the worker remains physically blocked after the caller returns, before
releasing the lease. Each subprocess propagates/asserts forced-lazy mode. There are no synthetic
recorded states/receipts, replaced drivers, mocked migration steps or private production probes.
Kernel waits, descriptors and stderr are independent actual observations, not a task flag.

Linux file-lease/proc support is required for this test mechanism. It does not qualify other
filesystems/OSs, global loop shutdown, failed physical close, WAL death or durable host loss.
No historical JSON is authored/regenerated here; references come from `../role-interruption/`.
