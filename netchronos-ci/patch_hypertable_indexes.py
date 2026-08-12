#!/usr/bin/env python3
"""Fail-closed compatibility patch for hot indexes on TimescaleDB hypertables.

TimescaleDB 2.29.1 hypertables reject CREATE INDEX CONCURRENTLY. NetChronos hot
indexes are physical actions on the telemetry hypertable, so this patch uses
ordinary CREATE INDEX. The actual blocking/build wall time remains inside the
measured reconfiguration cost; no cost is hidden or estimated away.
"""
from pathlib import Path

root = Path.cwd()
p = root / 'src/netchronos/design.py'
s = p.read_text(encoding='utf-8')
replacements = {
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tel_src_time':
        'CREATE INDEX IF NOT EXISTS idx_tel_src_time',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tel_dst_time':
        'CREATE INDEX IF NOT EXISTS idx_tel_dst_time',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tel_src_dst_time':
        'CREATE INDEX IF NOT EXISTS idx_tel_src_dst_time',
}
changed = False
for old, new in replacements.items():
    if old in s:
        s = s.replace(old, new)
        changed = True
    elif new not in s:
        raise SystemExit(f'expected index DDL marker missing: {old}')
p.write_text(s, encoding='utf-8')

# Fail closed: all hypertable hot-index DDL must now be non-concurrent.
import sys
sys.path.insert(0, str(root/'src'))
from netchronos.design import PhysicalDesign, initial_design_sql, layout_change_sql

d = PhysicalDesign(segmentby='src_ip', orderby='time_desc', hot_index='src_time')
sql = '\n'.join(initial_design_sql(d))
if 'CREATE INDEX IF NOT EXISTS idx_tel_src_time' not in sql or 'CONCURRENTLY' in sql:
    raise SystemExit('initial hot-index DDL is not TimescaleDB-compatible')
old = PhysicalDesign(segmentby='src_ip', orderby='time_desc', hot_index='none')
sql2 = '\n'.join(layout_change_sql(old, d))
if 'CREATE INDEX IF NOT EXISTS idx_tel_src_time' not in sql2 or 'CONCURRENTLY' in sql2:
    raise SystemExit('adaptive hot-index DDL is not TimescaleDB-compatible')

print('hypertable-index patch PASS: hot-index creation is non-concurrent and measured')
