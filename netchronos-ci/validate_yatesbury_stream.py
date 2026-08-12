#!/usr/bin/env python3
"""Fail-closed, memory-bounded validation of a processed Yatesbury scenario Parquet."""
from __future__ import annotations
import argparse, hashlib, json, pathlib
import pandas as pd
import pyarrow.parquet as pq

REQUIRED_COLUMNS={
    'ts','src_ip','dst_ip','src_port','dst_port','protocol','direction','decision',
    'flow_state','packets_sent','bytes_sent','packets_received','bytes_received',
    'attack_label','scenario','trace_offset_s','pilot_split'
}

def sha256(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--data',required=True); p.add_argument('--manifest',required=True); p.add_argument('--require-scenario',required=True); p.add_argument('--batch-rows',type=int,default=250000); a=p.parse_args()
    path=pathlib.Path(a.data); mp=pathlib.Path(a.manifest)
    if not path.exists() or not mp.exists(): raise SystemExit('processed dataset/manifest missing')
    manifest=json.loads(mp.read_text(encoding='utf-8'))
    digest=sha256(path)
    if digest!=manifest.get('processed_sha256'): raise SystemExit('processed dataset SHA-256 differs from manifest')
    pf=pq.ParquetFile(path); missing=REQUIRED_COLUMNS-set(pf.schema_arrow.names)
    if missing: raise SystemExit(f'missing processed columns: {sorted(missing)}')
    if pf.metadata.num_rows<=0: raise SystemExit('processed trace is empty')
    total=attack=pilot=test=0; null_bad=False; labels=set(); scenarios=set(); protocols=set(); pilot_max=None; test_min=None; src=set(); dst=set(); ts_min=None; ts_max=None
    cols=sorted(REQUIRED_COLUMNS)
    for batch in pf.iter_batches(batch_size=a.batch_rows,columns=cols):
        df=batch.to_pandas()
        total+=len(df)
        if df['ts'].isna().any() or df['src_ip'].isna().any() or df['dst_ip'].isna().any(): null_bad=True
        labels.update(int(x) for x in pd.unique(df['attack_label']))
        scenarios.update(str(x) for x in pd.unique(df['scenario']))
        protocols.update(int(x) for x in pd.unique(df['protocol']))
        attack+=int(df['attack_label'].sum())
        ps=df['pilot_split'].astype(bool); pilot+=int(ps.sum()); test+=int((~ps).sum())
        if ps.any():
            v=df.loc[ps,'ts'].max(); pilot_max=v if pilot_max is None or v>pilot_max else pilot_max
        if (~ps).any():
            v=df.loc[~ps,'ts'].min(); test_min=v if test_min is None or v<test_min else test_min
        lo,hi=df['ts'].min(),df['ts'].max(); ts_min=lo if ts_min is None or lo<ts_min else ts_min; ts_max=hi if ts_max is None or hi>ts_max else ts_max
        src.update(df['src_ip'].astype(str).unique().tolist()); dst.update(df['dst_ip'].astype(str).unique().tolist())
    if total!=pf.metadata.num_rows: raise SystemExit(f'streamed rows {total} != parquet metadata {pf.metadata.num_rows}')
    if null_bad: raise SystemExit('null timestamp/IP in processed trace')
    if not labels.issubset({0,1}): raise SystemExit(f'attack_label contains values outside {{0,1}}: {sorted(labels)}')
    if scenarios!={a.require_scenario}: raise SystemExit(f'expected only scenario {a.require_scenario}, found {sorted(scenarios)}')
    if pilot<=0 or test<=0: raise SystemExit(f'{a.require_scenario}: pilot/test chronological split is degenerate')
    if pilot_max>test_min: raise SystemExit(f'{a.require_scenario}: chronological pilot/test leakage')
    if a.require_scenario=='normal_synflood_ddos' and attack<=0: raise SystemExit('SYN-flood DDoS scenario contains no joined positive labels')
    mstat=manifest.get('scenarios',{}).get(a.require_scenario)
    if not mstat: raise SystemExit('required scenario absent from manifest')
    if int(mstat['rows'])!=total or int(manifest.get('processed_rows',-1))!=total: raise SystemExit('manifest row count mismatch')
    if int(mstat.get('attack_rows',-1))!=attack: raise SystemExit('manifest attack-row count mismatch')
    report={'status':'PASS','scenario':a.require_scenario,'rows':total,'attack_rows':attack,'unique_src':len(src),'unique_dst':len(dst),'start':ts_min.isoformat(),'end':ts_max.isoformat(),'pilot_rows':pilot,'test_rows':test,'protocol_values':sorted(protocols),'sha256':digest}
    print(json.dumps(report,indent=2))
if __name__=='__main__': main()
