#!/usr/bin/env python3
"""Execute exactly one deterministic pilot candidate across the frozen five pilot phases."""
from __future__ import annotations
import argparse, json, pathlib, sys
from datetime import datetime, timezone
import pandas as pd
import psycopg, yaml

ROOT=pathlib.Path.cwd()
sys.path.insert(0,str(ROOT/'scripts'))
from run_pilot import PILOT_PHASES, diverse_sample, prefill
from run_experiment import dsn_for, reset_schema, run_phase, storage_mb, context_for, slo_for, query_profile
from netchronos.candidates import enumerate_designs
from netchronos.db import apply_initial_design, server_metadata
from netchronos.objective import Metrics, constraint_margin, normalized_cost


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--candidate-index',type=int,required=True)
    ap.add_argument('--matrix',default='configs/experiment_matrix.yaml')
    ap.add_argument('--data',default='data/processed/yatesbury.parquet')
    ap.add_argument('--calibration',default='results/calibration.json')
    ap.add_argument('--out',required=True)
    ap.add_argument('--candidates',type=int,default=36)
    ap.add_argument('--seconds',type=int,default=30)
    ap.add_argument('--prefill-event-hours',type=int,default=72)
    a=ap.parse_args()
    cfg=yaml.safe_load(open(a.matrix))
    designs=diverse_sample(enumerate_designs(cfg['candidate_space']),a.candidates,cfg['seed'])
    di=a.candidate_index
    if di<0 or di>=len(designs): raise SystemExit(f'candidate-index {di} outside 0..{len(designs)-1}')
    d=designs[di]
    df=pd.read_parquet(a.data)
    cal=json.loads(pathlib.Path(a.calibration).read_text()); reference=float(cal['reference_ingest_rows_s'])
    out=pathlib.Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    dsn=dsn_for('ts_pilot_best'); epoch=datetime(2026,1,1,tzinfo=timezone.utc)
    normal=df[(df.scenario=='normal') & (df.pilot_split)].copy()
    if normal.empty: raise SystemExit('pilot normal trace empty')
    with out.open('w',encoding='utf-8') as fh:
        for pi,phase in enumerate(PILOT_PHASES):
            sub=df[(df.scenario==phase['scenario']) & (df.pilot_split)].copy()
            if sub.empty: raise RuntimeError(f"pilot rows missing for {phase['scenario']}")
            with psycopg.connect(dsn) as conn:
                reset_schema(conn,'ts_pilot_best')
                rr0=apply_initial_design(conn,d)
                if not rr0.success: raise RuntimeError(rr0.error)
                prefill_rows,prefill_reconfig,prefill_start=prefill(conn,normal,d,epoch,a.prefill_event_hours)
                meta=server_metadata(conn)
            profile_name,profile_weights=query_profile(cfg,phase)
            qps=float(cfg['replay']['query_qps'][profile_name])
            target=reference*float(phase['capacity_fraction'])
            phase_run=dict(phase); phase_run['_query_profile_weights']=profile_weights
            state,context=context_for(sub,phase_run,target,qps,cfg.get('query_profiles'))
            slo=slo_for(cfg,target)
            res=run_phase(dsn,sub,phase_run,epoch,target,qps,a.seconds,d,cfg['seed']+di*100+pi,resource_service='timescaledb',query_min_ts=prefill_start)
            with psycopg.connect(dsn) as conn: sm=storage_mb(conn)
            deployment_reconfig_s=rr0.elapsed_s+prefill_reconfig
            m=Metrics(res['p95_ms'],res['p99_ms'],res['ingest_rows_s'],sm,res['cagg_staleness_s'],res['cpu_pct_mean'],res['read_mb_s']+res['write_mb_s'],0.0)
            cost=normalized_cost(m,slo); margin=constraint_margin(m,slo)
            if res.get('errors'):
                cost=max(float(cost),float(cfg.get('failure_penalty_cost',10.0))); margin=min(float(margin),-1.0)
            rec={**res,'stage':'pilot','candidate_id':di,'phase':phase['name'],'scenario':phase['scenario'],'design':d.as_dict(),'context':context.tolist(),'cost':cost,'constraint_margin':margin,'storage_mb':sm,'prefill_rows':prefill_rows,'deployment_reconfig_s':deployment_reconfig_s,'metadata':meta}
            fh.write(json.dumps(rec,default=str)+'\n'); fh.flush()
    lines=sum(1 for _ in out.open())
    if lines!=len(PILOT_PHASES): raise SystemExit(f'pilot candidate {di}: expected {len(PILOT_PHASES)} observations, got {lines}')
    print(json.dumps({'status':'PASS','candidate_id':di,'observations':lines,'out':str(out)}))

if __name__=='__main__': main()
