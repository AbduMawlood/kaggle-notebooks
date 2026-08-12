#!/usr/bin/env python3
"""Combine 36 independently produced candidate pilot JSONLs deterministically."""
from __future__ import annotations
import argparse, json, site
from pathlib import Path

def register_project_src():
    src=(Path.cwd()/'src').resolve()
    if not (src/'netchronos'/'__init__.py').exists(): raise SystemExit(f'NetChronos package missing at {src}')
    site_dirs=site.getsitepackages()
    if not site_dirs: raise SystemExit('Python site-packages directory not found')
    pth=Path(site_dirs[0])/'netchronos_ci_src.pth'
    pth.write_text(str(src)+'\n',encoding='utf-8')
    print(f'registered NetChronos source path: {src} -> {pth}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-root',default='pilot-artifacts'); ap.add_argument('--out',default='results/raw/pilot.jsonl'); ap.add_argument('--candidates',type=int,default=36); ap.add_argument('--phases',type=int,default=5); a=ap.parse_args()
    root=Path(a.input_root); files=list(root.rglob('pilot_c*.jsonl'))
    if len(files)!=a.candidates: raise SystemExit(f'expected {a.candidates} pilot files, found {len(files)}')
    by_id={}
    for p in files:
        rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
        ids={int(r['candidate_id']) for r in rows}
        if len(ids)!=1: raise SystemExit(f'{p}: mixed candidate ids {ids}')
        cid=next(iter(ids))
        if cid in by_id: raise SystemExit(f'duplicate candidate id {cid}')
        if len(rows)!=a.phases: raise SystemExit(f'{p}: expected {a.phases} rows, got {len(rows)}')
        by_id[cid]=rows
    if sorted(by_id)!=list(range(a.candidates)): raise SystemExit(f'candidate ids incomplete: {sorted(by_id)}')
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as fh:
        for cid in range(a.candidates):
            for r in by_id[cid]: fh.write(json.dumps(r,default=str)+'\n')
    n=sum(1 for _ in out.open())
    expected=a.candidates*a.phases
    if n!=expected: raise SystemExit(f'aggregated rows {n} != {expected}')
    register_project_src()
    print(json.dumps({'status':'PASS','candidates':a.candidates,'observations':n,'out':str(out)}))
if __name__=='__main__': main()
