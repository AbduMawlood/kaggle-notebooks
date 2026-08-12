#!/usr/bin/env python3
"""Fail-closed compatibility patch for TimescaleDB segment/order legality.

TimescaleDB 2.29.1 rejects physical layouts where a column appears in both
segmentby and orderby. This patch removes those engine-illegal states from the
NetChronos executable design space, changes fixed/anchor/smoke designs to legal
representatives, and verifies the resulting 2,880-design action space.

This is a correctness amendment made before any target-engine performance
results exist. It does not alter Yatesbury values, workload phases, SLOs,
baselines, repetitions, or statistical endpoints.
"""
from pathlib import Path
import sys

ROOT = Path.cwd()

def replace_once(path: Path, old: str, new: str):
    s = path.read_text(encoding='utf-8')
    if old not in s:
        if new in s:
            return
        raise SystemExit(f'{path}: expected patch marker not found')
    path.write_text(s.replace(old, new, 1), encoding='utf-8')

# 1) PhysicalDesign.validate(): reject overlap explicitly.
p = ROOT/'src/netchronos/design.py'
old = '''        if self.hot_index not in _INDEX_DDL:\n            raise ValueError("unsupported hot index")\n        # A 6-hour summary cannot serve a 5-minute dashboard. This is allowed\n'''
new = '''        if self.hot_index not in _INDEX_DDL:\n            raise ValueError("unsupported hot index")\n        seg_raw = _SEGMENT[self.segmentby]\n        seg_cols = set(seg_raw.split(',')) if seg_raw else set()\n        order_cols = {part.strip().split()[0] for part in _ORDER[self.orderby].split(',')}\n        overlap = seg_cols & order_cols\n        if overlap:\n            raise ValueError(\n                "TimescaleDB forbids a column from appearing in both segmentby and orderby: "\n                + ",".join(sorted(overlap))\n            )\n        # A 6-hour summary cannot serve a 5-minute dashboard. This is allowed\n'''
replace_once(p, old, new)

# 2) Candidate enumeration: skip only this documented engine-illegal class.
p = ROOT/'src/netchronos/candidates.py'
old = '''        d=PhysicalDesign(int(chunk),int(age),str(seg),str(order),int(bucket),int(refresh),str(idx)).validate()\n        key=tuple(d.as_dict().values())\n'''
new = '''        d=PhysicalDesign(int(chunk),int(age),str(seg),str(order),int(bucket),int(refresh),str(idx))\n        try:\n            d=d.validate()\n        except ValueError as e:\n            if "both segmentby and orderby" in str(e):\n                continue\n            raise\n        key=tuple(d.as_dict().values())\n'''
replace_once(p, old, new)

# 3) Fixed and representative designs: preserve segment key, use time-only order.
repls = {
    ROOT/'scripts/integration_smoke.py': [
        ("PhysicalDesign(6,2,'src_ip','time_src',5,5,'src_time')",
         "PhysicalDesign(6,2,'src_ip','time_desc',5,5,'src_time')")],
    ROOT/'scripts/run_pilot.py': [
        ("PhysicalDesign(6,2,'src_ip','time_src',60,30,'none')",
         "PhysicalDesign(6,2,'src_ip','time_desc',60,30,'none')"),
        ("PhysicalDesign(6,12,'src_ip','time_src',60,30,'src_time')",
         "PhysicalDesign(6,12,'src_ip','time_desc',60,30,'src_time')")],
    ROOT/'scripts/run_experiment.py': [
        ("PhysicalDesign(6,2,'src_ip','time_src',60,30,'none')",
         "PhysicalDesign(6,2,'src_ip','time_desc',60,30,'none')"),
        ("PhysicalDesign(6,12,'src_ip','time_src',60,30,'src_time')",
         "PhysicalDesign(6,12,'src_ip','time_desc',60,30,'src_time')")],
}
for path, pairs in repls.items():
    s = path.read_text(encoding='utf-8')
    changed = False
    for old, new in pairs:
        if old in s:
            s = s.replace(old, new)
            changed = True
        elif new not in s:
            raise SystemExit(f'{path}: fixed-design marker missing: {old}')
    if changed:
        path.write_text(s, encoding='utf-8')

# 4) Runtime verification of legality and exact executable-space cardinality.
sys.path.insert(0, str(ROOT/'src'))
import yaml
from netchronos.design import PhysicalDesign
from netchronos.candidates import enumerate_designs
cfg = yaml.safe_load((ROOT/'configs/experiment_matrix.yaml').read_text())

designs = enumerate_designs(cfg['candidate_space'])
if len(designs) != 2880:
    raise SystemExit(f'legal candidate count mismatch: expected 2880, got {len(designs)}')
for d in designs:
    d.validate()
try:
    PhysicalDesign(segmentby='src_ip', orderby='time_src').validate()
except ValueError as e:
    if 'both segmentby and orderby' not in str(e):
        raise
else:
    raise SystemExit('illegal segment/order overlap was not rejected')

print('design-legality patch PASS: 2880 executable TimescaleDB-legal designs')
