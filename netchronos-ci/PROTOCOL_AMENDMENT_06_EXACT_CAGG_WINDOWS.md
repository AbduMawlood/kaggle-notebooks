# Protocol Amendment 06 — Exact Continuous-Aggregate Window Semantics

**Status:** correctness amendment before target-engine performance results  
**Target engine:** PostgreSQL 17 + TimescaleDB 2.29.1  
**Reason discovered:** raw-vs-CAGG semantic integration gate

## Trigger

After the target engine accepted the legal physical layout, supported hot-index
DDL, and out-of-transaction continuous-aggregate refresh, the semantic gate
reported equal result cardinality but unequal values for a dashboard query:

`CAGG semantic mismatch: raw_rows=5 cagg_rows=5`

The raw query uses an exact half-open interval `[start,end)`. A bucketed summary
cannot preserve an arbitrary non-bucket-aligned endpoint merely by filtering on
its bucket timestamp, because a partial first/final bucket can contain rows
outside the requested interval.

No target-engine performance or comparative result existed when this amendment
was made.

## Amendment

Summary routing now uses the continuous aggregate only for **fully covered
interior CAGG buckets**. Telemetry belonging to partial boundary regions is
recomputed from the raw hypertable using the original exact `[start,end)`
predicates. The summary and raw pieces are then combined at the requested query
granularity.

This applies to both dashboard and historical summary-eligible queries. The
public query API remains two timestamps, requested horizons are unchanged, and
queries whose requested granularity is coarser/finer than the available summary
continue to fall back exactly as before.

This is not a relaxation of the semantic check. The raw-table query remains the
reference answer and the CAGG route must match it exactly.

## Unchanged protocol elements

The Yatesbury trace and labels, workload windows, query arrival rates, SLOs,
15 independent repetitions, legal 2,880-design physical space, baseline set,
controller thresholds, and statistical endpoints are unchanged.

## Validation

The corrected implementation passes **33/33 local tests** and complete source
and script compilation. CI additionally fails closed unless generated dashboard
and historical summary routes contain both the CAGG interior path and exact raw
boundary correction predicates.
