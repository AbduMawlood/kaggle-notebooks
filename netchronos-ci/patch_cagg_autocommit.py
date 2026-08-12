#!/usr/bin/env python3
"""Execute TimescaleDB continuous-aggregate refresh calls in autocommit mode.

TimescaleDB 2.29.1 requires refresh_continuous_aggregate() to run outside an
explicit transaction block. The checksum-pinned bundle already contains the
fail-closed execute_statements() autocommit helper; this patch routes both the
semantic smoke refresh and the actual benchmark CAGG worker through that helper.
No refresh cadence, time window, query semantics, or measured duration is changed.
"""
from pathlib import Path

root = Path.cwd()

# Semantic integration smoke.
p = root/'scripts/integration_smoke.py'
s = p.read_text(encoding='utf-8')
old = "        with conn.cursor() as cur: cur.execute(q)\n        conn.commit()\n"
new = "        execute_statements(conn,[q])\n"
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('integration_smoke.py: refresh target not found')
p.write_text(s, encoding='utf-8')

# Actual benchmark CAGG worker.
p = root/'scripts/run_experiment.py'
s = p.read_text(encoding='utf-8')
old = "                    with conn.cursor() as cur: cur.execute(q)\n                    conn.commit(); materialized_until=refresh_end; refresh_s.append(time.perf_counter()-t0)\n"
new = "                    execute_statements(conn,[q])\n                    materialized_until=refresh_end; refresh_s.append(time.perf_counter()-t0)\n"
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('run_experiment.py: CAGG worker refresh target not found')
p.write_text(s, encoding='utf-8')

# Fail closed: every runtime refresh call in these files must use the helper.
for path in (root/'scripts/integration_smoke.py', root/'scripts/run_experiment.py'):
    text = path.read_text(encoding='utf-8')
    if 'refresh_cagg_sql' not in text:
        raise SystemExit(f'{path}: refresh SQL disappeared unexpectedly')
if 'execute_statements(conn,[q])' not in (root/'scripts/integration_smoke.py').read_text(encoding='utf-8'):
    raise SystemExit('smoke refresh is not routed through autocommit helper')
if 'execute_statements(conn,[q])' not in (root/'scripts/run_experiment.py').read_text(encoding='utf-8'):
    raise SystemExit('benchmark refresh is not routed through autocommit helper')

print('CAGG-autocommit patch PASS: smoke and benchmark refresh calls are out-of-transaction')
