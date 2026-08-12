#!/usr/bin/env python3
"""Fail-closed memory patch for frozen benchmark scripts.

Only data-loading mechanics are changed: pandas/pyarrow predicate filters are applied
before materialization. No row selection differs from the existing downstream Boolean
filters, and no benchmark constants, SLOs, designs, seeds, or measurements are changed.
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
replace_once(
    root/'scripts'/'integration_smoke.py',
    "a=p.parse_args(); df=pd.read_parquet(a.data)",
    "a=p.parse_args(); df=pd.read_parquet(a.data, filters=[('scenario','==','normal'),('pilot_split','==',True)])",
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

print('memory-loader patch complete: semantics unchanged, predicate pushdown enabled')
