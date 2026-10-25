# Current comparative runtime and capacity baseline

Measurement protocol for #548. Completed findings and raw evidence are added
only after this source revision is committed and measured with a clean tree.

The protocol compares real raw-driver, snekql and SQLAlchemy Core pools on both
backends. It varies pool capacity one/four, concurrency below/at/above capacity,
32/4096-byte payloads, point reads, joins, acknowledged/read-back bulk writes,
stream batches 64/256, and counting observation off/on. Every adapter prepares
all configured slots and verifies effective policy before timing.

Six rounds cover all six adapter permutations. Observer contrasts additionally
use fresh-process off/on then on/off blocks. Primary timing, acquisition
diagnostics and scoped memory profiles remain separate. All workloads validate
actual returned values and completed work. This is a closed-loop local baseline,
not an arrival-rate/SLO, durability-equivalence-between-engines, exhaustive
scheduler, production instrumentation or universal pool-sizing certification.

See [the command contract](comparison.md) and the
[historical baseline](findings.md). Interpreter, dependencies, engines and MariaDB
payload-column capacity differ from the older baseline; do not infer a library
speedup from cross-date ratios. No timing threshold is a CI gate.
