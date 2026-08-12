# Protocol Amendment 03 — TimescaleDB Segment/Order Legality

**Status:** correctness amendment before target-engine performance results  
**Target engine:** PostgreSQL 17 + TimescaleDB 2.29.1  
**Reason discovered:** semantic integration gate

## Trigger

The target-engine semantic gate rejected a representative physical design because
`src_ip` appeared in both `timescaledb.segmentby` and `timescaledb.orderby`.
TimescaleDB 2.29.1 rejects any physical layout in which the same column is used
for both functions.

No target-engine latency, throughput, SLO, storage, resource, or comparative
performance result had been generated when this amendment was made. The failure
occurred before calibration, pilot selection, and all confirmatory target runs.

## Amendment

The executable action space now excludes every segment/order pair with an
overlapping column. The valid pairs are:

- `none` × `{time_desc, time_src, time_dst}`
- `src_ip` × `{time_desc, time_dst}`
- `dst_ip` × `{time_desc, time_src}`
- `src_dst` × `{time_desc}`

The canonical CAGG-refresh collapse remains unchanged. Consequently, the legal
finite action space changes from 4,320 syntactic combinations to **2,880
engine-executable physical designs**.

The representative smoke-test design, pilot anchors, the Cloudflare-inspired
static baseline, and the missing-pilot fallback retain `src_ip` segmentation but
use `time_desc` ordering rather than the engine-illegal `time_src` ordering.

## Unchanged protocol elements

This amendment does **not** change:

- Yatesbury source values or authoritative labels;
- chronological 20/80 pilot/evaluation split;
- workload phases or query-profile mixtures;
- 15 independent repetitions;
- SLO thresholds;
- equal resource/durability controls;
- baseline set;
- primary endpoints;
- statistical tests or multiplicity correction;
- controller drift, dwell, RBCR, uncertainty, or rollback thresholds.

## Validation

The corrected implementation was exercised locally with the full software test
suite: **30/30 tests passed**. Runtime verification also asserts exactly 2,880
legal candidates and fails closed if any segment/order overlap reaches the
optimizer.
