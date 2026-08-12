#!/usr/bin/env python3
"""Make continuous-aggregate routing exactly preserve raw [start,end) semantics.

A bucketed summary cannot, by itself, answer arbitrary non-bucket-aligned query
windows: filtering on the bucket timestamp can include data outside the raw
window in the first or final partial bucket. This pre-results correctness patch
uses the CAGG only for fully covered interior buckets and recomputes partial edge
buckets from raw telemetry, then combines the pieces.

The public query API remains two parameters. Requested time windows, query
families, aggregation granularity, SLOs, and workload arrival processes are
unchanged.
"""
from pathlib import Path
import sys

p=Path('src/netchronos/workload.py')
s=p.read_text(encoding='utf-8')
old='''def query_sql(spec: QuerySpec, cagg_bucket_minutes: int=0) -> tuple[str,bool]:\n    """Route only queries whose requested granularity is answerable exactly by the summary."""\n    if not cagg_bucket_minutes or spec.min_summary_bucket_min is None:\n        return spec.sql_raw,False\n    if cagg_bucket_minutes > spec.min_summary_bucket_min:\n        return spec.sql_raw,False\n    if spec.name=='historical':\n        return """SELECT date_bin(INTERVAL '1 hour', bucket, TIMESTAMPTZ '2000-01-01') b, protocol,\n sum(total_bytes) FROM telemetry_cagg WHERE bucket >= %s AND bucket < %s GROUP BY 1,2 ORDER BY 1,2""",True\n    if spec.name=='dashboard' and cagg_bucket_minutes==5:\n        return "SELECT bucket, sum(total_bytes) FROM telemetry_cagg WHERE bucket >= %s AND bucket < %s GROUP BY 1 ORDER BY 1",True\n    return spec.sql_raw,False\n'''
new='''def _exact_cagg_bounds_sql(bucket_minutes: int) -> str:\n    """CTEs defining exact [start,end) coverage for a bucketed summary.\n\n    A continuous aggregate stores whole buckets. Arbitrary query windows can\n    therefore be answered exactly only by combining summary rows for fully\n    covered interior buckets with raw telemetry for partial boundary regions.\n    """\n    m=int(bucket_minutes)\n    return f"""WITH p AS (\n SELECT %s::timestamptz AS s, %s::timestamptz AS e\n), b AS (\n SELECT s,e,\n        date_bin(INTERVAL '{m} minutes', s, TIMESTAMPTZ '2000-01-01') AS sf,\n        date_bin(INTERVAL '{m} minutes', e, TIMESTAMPTZ '2000-01-01') AS ef\n FROM p\n), cuts AS (\n SELECT s,e,\n        CASE WHEN s=sf THEN sf ELSE sf+INTERVAL '{m} minutes' END AS full_start,\n        ef AS full_end\n FROM b\n)"""\n\n\ndef query_sql(spec: QuerySpec, cagg_bucket_minutes: int=0) -> tuple[str,bool]:\n    """Route only queries that the summary can answer exactly.\n\n    Fully covered interior buckets come from ``telemetry_cagg``; partial edge\n    buckets are recomputed from raw telemetry so the original [start,end)\n    semantics are preserved for arbitrary endpoints.\n    """\n    if not cagg_bucket_minutes or spec.min_summary_bucket_min is None:\n        return spec.sql_raw,False\n    if cagg_bucket_minutes > spec.min_summary_bucket_min:\n        return spec.sql_raw,False\n    cte=_exact_cagg_bounds_sql(cagg_bucket_minutes)\n    if spec.name=='historical':\n        sql=cte+f"""\n, pieces AS (\n SELECT date_bin(INTERVAL '1 hour', c.bucket, TIMESTAMPTZ '2000-01-01') AS b,\n        c.protocol, sum(c.total_bytes)::numeric AS total_bytes\n FROM telemetry_cagg c CROSS JOIN cuts\n WHERE c.bucket >= cuts.full_start AND c.bucket < cuts.full_end\n GROUP BY 1,2\n UNION ALL\n SELECT date_bin(INTERVAL '1 hour', t.ts, TIMESTAMPTZ '2000-01-01') AS b,\n        t.protocol,\n        sum(COALESCE(t.bytes_sent,0)+COALESCE(t.bytes_received,0))::numeric AS total_bytes\n FROM telemetry t CROSS JOIN cuts\n WHERE t.ts >= cuts.s AND t.ts < cuts.e\n   AND (t.ts < cuts.full_start OR t.ts >= cuts.full_end)\n GROUP BY 1,2\n)\nSELECT b,protocol,sum(total_bytes) AS total_bytes\nFROM pieces GROUP BY 1,2 ORDER BY 1,2"""\n        return sql,True\n    if spec.name=='dashboard' and cagg_bucket_minutes==5:\n        sql=cte+f"""\n, pieces AS (\n SELECT c.bucket AS b, sum(c.total_bytes)::numeric AS total_bytes\n FROM telemetry_cagg c CROSS JOIN cuts\n WHERE c.bucket >= cuts.full_start AND c.bucket < cuts.full_end\n GROUP BY 1\n UNION ALL\n SELECT date_bin(INTERVAL '5 minutes', t.ts, TIMESTAMPTZ '2000-01-01') AS b,\n        sum(COALESCE(t.bytes_sent,0)+COALESCE(t.bytes_received,0))::numeric AS total_bytes\n FROM telemetry t CROSS JOIN cuts\n WHERE t.ts >= cuts.s AND t.ts < cuts.e\n   AND (t.ts < cuts.full_start OR t.ts >= cuts.full_end)\n GROUP BY 1\n)\nSELECT b,sum(total_bytes) AS total_bytes\nFROM pieces GROUP BY 1 ORDER BY 1"""\n        return sql,True\n    return spec.sql_raw,False\n'''
if old in s:
    s=s.replace(old,new,1)
elif new not in s:
    raise SystemExit('workload.py: expected query_sql block not found')
p.write_text(s,encoding='utf-8')

# Fail closed on the actual generated routes.
sys.path.insert(0,str(Path('src').resolve()))
from netchronos.workload import QUERIES, query_sql
for name,bucket in [('dashboard',5),('historical',60)]:
    sql,used=query_sql(QUERIES[name],bucket)
    if not used or 'telemetry_cagg' not in sql or 'FROM telemetry t' not in sql:
        raise SystemExit(f'{name}: exact hybrid CAGG route not installed')
    if 'full_start' not in sql or 'full_end' not in sql or 't.ts >= cuts.s AND t.ts < cuts.e' not in sql:
        raise SystemExit(f'{name}: edge-correction predicates missing')
_,used=query_sql(QUERIES['dashboard'],60)
if used:
    raise SystemExit('dashboard was incorrectly routed to a coarse 60-minute CAGG')
print('exact-CAGG-query patch PASS: full interior summary + raw boundary correction')
