#!/usr/bin/env python3
"""Fail-closed memory/CI patch for frozen benchmark scripts.

Only data-loading/sampling mechanics are changed. Parquet predicates are pushed down
before materialization, and the smoke-test sample is time-stratified over the same
normal pilot interval so that it can exercise closed continuous-aggregate buckets.
No source row is synthesized; no benchmark constant, SLO, design, seed, query, or
measured outcome is changed.
"""
from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    s=path.read_text(encoding='utf-8')
    n=s.count(old)
    if n!=1:
        raise SystemExit(f'{path}: expected exactly one patch target, found {n}: {old[:80]!r}')
    path.write_text(s.replace(old,new,1),encoding='utf-8')
    print(f'patched {path}')

root=Path.cwd()

# Smoke test already selects normal+pilot immediately after loading; push that same
# predicate into Parquet before pandas materializes the frame.
smoke=root/'scripts'/'integration_smoke.py'
replace_once(
    smoke,
    "a=p.parse_args(); df=pd.read_parquet(a.data)",
    "a=p.parse_args(); df=pd.read_parquet(a.data, filters=[('scenario','==','normal'),('pilot_split','==',True)])",
)
# The frozen smoke test used head(N), which on dense NSG flow logs can cover less than
# 10 minutes even for N=100k. Select at most the same N *real* rows, evenly over the
# already defined <=24 h smoke window, so CAGG closed-bucket semantics are testable.
replace_once(
    smoke,
    "x=span.head(a.rows)",
    "n=min(int(a.rows),len(span))\n    if n < 2: raise SystemExit('Smoke slice has fewer than two real rows')\n    x=span if len(span)<=n else span.iloc[[int(i*(len(span)-1)/(n-1)) for i in range(n)]].copy()",
)

# Calibration likewise uses only normal pilot rows.
replace_once(
    root/'scripts'/'calibrate.py',
    "df=pd.read_parquet(a.data); df=df[(df.scenario=='normal') & (df.pilot_split)]",
    "df=pd.read_parquet(a.data, filters=[('scenario','==','normal'),('pilot_split','==',True)])",
)

# Confirmatory runner previously held all scenarios and both splits for the whole run.
# It now materializes only the current held-out scenario at each phase. This is exactly
# equivalent to the original phase Boolean selection.
replace_once(
    root/'scripts'/'run_experiment.py',
    "cfg=yaml.safe_load(open(a.matrix)); df=pd.read_parquet(a.data)",
    "cfg=yaml.safe_load(open(a.matrix)); df=None",
)
replace_once(
    root/'scripts'/'run_experiment.py',
    "sub=df[(df.scenario==phase['scenario']) & (~df.pilot_split)].copy()",
    "sub=pd.read_parquet(a.data, filters=[('scenario','==',phase['scenario']),('pilot_split','==',False)]).copy()",
)

print('memory/CI patch complete: predicate pushdown + time-stratified real-row smoke sample enabled')
