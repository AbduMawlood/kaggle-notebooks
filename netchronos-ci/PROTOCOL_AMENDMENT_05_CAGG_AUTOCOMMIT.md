# Protocol Amendment 05 — Continuous-Aggregate Refresh Transaction Boundary

**Status:** correctness amendment before target-engine performance results  
**Target engine:** PostgreSQL 17 + TimescaleDB 2.29.1  
**Reason discovered:** semantic integration gate

## Trigger

The target semantic gate reached continuous-aggregate materialization and
TimescaleDB rejected the refresh with:

`refresh_continuous_aggregate() cannot run inside a transaction block`

No target performance or comparative result existed when this amendment was
made.

## Amendment

Both the semantic smoke test and the actual benchmark CAGG refresh worker route
`CALL refresh_continuous_aggregate(...)` through the existing fail-closed
autocommit execution helper. Refresh windows, event-time watermark logic,
refresh cadence, real-time aggregate mode, query routing, and staleness
measurement remain unchanged.

The measured refresh duration still includes the complete server call. No
refresh cost is removed, estimated, or hidden.

## Unchanged protocol elements

The Yatesbury data and labels, 20/80 split, six workload regimes, SLOs, 15
independent repetitions, legal physical-design space, baseline set, controller
thresholds, and statistical analysis are unchanged.

## Validation

The corrected implementation retains **31/31 passing local tests** and compiles
all source and benchmark scripts. CI fails closed unless the semantic and
benchmark refresh paths both use the out-of-transaction execution helper.
