# Protocol Amendment 04 — Hypertable Hot-Index Creation

**Status:** correctness amendment before target-engine performance results  
**Target engine:** PostgreSQL 17 + TimescaleDB 2.29.1  
**Reason discovered:** semantic integration gate

## Trigger

After the legal segment/order action-space correction, TimescaleDB 2.29.1
rejected the representative hot-index action with:

`hypertables do not support concurrent index creation`

The generic PostgreSQL DDL template used `CREATE INDEX CONCURRENTLY`, whereas
NetChronos hot indexes are created on the TimescaleDB `telemetry` hypertable.
No target-engine latency, throughput, SLO, resource, storage, or comparative
performance result existed when this amendment was made.

## Amendment

All NetChronos hot-index actions on the TimescaleDB hypertable use ordinary
`CREATE INDEX IF NOT EXISTS` rather than `CREATE INDEX CONCURRENTLY`.

This does **not** make index creation free. Its complete wall-clock build time,
locking/blocking consequences, resource consumption, and any associated SLO
exposure remain part of the measured reconfiguration cost. Thus the amendment
uses the operation actually supported by the target engine and, if anything,
makes the evaluation more conservative.

The plain PostgreSQL baselines retain their separately defined baseline index
DDL; no baseline is given an engine-incompatible operation.

## Unchanged protocol elements

This amendment does not change the real Yatesbury data, workload phases,
chronological split, 15 repetitions, SLO thresholds, candidate semantics,
baseline set, statistical endpoints, or NetChronos controller thresholds.

## Validation

The corrected code was exercised locally with **31/31 tests passing**. The CI
bootstrap also fails closed unless both initial and adaptive hypertable hot-index
DDL contain no `CONCURRENTLY` keyword.
