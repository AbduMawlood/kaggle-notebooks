#!/usr/bin/env python3
"""Combine independently validated Yatesbury scenario Parquets without full-frame materialization."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

EXPECTED_DEFAULT = ['normal','varying_load','normal_synflood_ddos','normal_udp_ddos']

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-root', default='scenario-artifacts')
    ap.add_argument('--out', default='data/processed/yatesbury.parquet')
    ap.add_argument('--manifest', default='data/processed/yatesbury_manifest.json')
    ap.add_argument('--scenario', action='append')
    ap.add_argument('--batch-rows', type=int, default=250000)
    a=ap.parse_args()
    expected=sorted(a.scenario or EXPECTED_DEFAULT)
    root=Path(a.input_root)
    manifests=list(root.rglob('yatesbury_*.manifest.json'))
    if len(manifests)!=len(expected):
        raise SystemExit(f'expected {len(expected)} scenario manifests, found {len(manifests)}')

    records=[]
    for mp in manifests:
        m=json.loads(mp.read_text(encoding='utf-8'))
        scenarios=m.get('scenarios') or {}
        if len(scenarios)!=1:
            raise SystemExit(f'{mp}: expected exactly one scenario, got {sorted(scenarios)}')
        scenario=next(iter(scenarios))
        pqpath=next(iter(mp.parent.glob(f'yatesbury_{scenario}.parquet')), None)
        if pqpath is None:
            raise SystemExit(f'{mp}: matching parquet missing for {scenario}')
        digest=sha256(pqpath)
        if digest!=m.get('processed_sha256'):
            raise SystemExit(f'{pqpath}: SHA-256 differs from scenario manifest')
        records.append((scenario,pqpath,m))
    found=sorted(x[0] for x in records)
    if found!=expected:
        raise SystemExit(f'scenario mismatch: expected={expected}, found={found}')

    out=Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    writer=None; schema=None; total=0; combined_scenarios={}; archives=[]; pilot_fraction=None
    try:
        for scenario,pqpath,m in sorted(records,key=lambda x:x[0]):
            pf=pq.ParquetFile(pqpath)
            if schema is None:
                schema=pf.schema_arrow
                writer=pq.ParquetWriter(out, schema, compression='snappy')
            elif not pf.schema_arrow.equals(schema, check_metadata=False):
                raise SystemExit(f'{pqpath}: schema differs from first scenario')
            scenario_rows=0
            for batch in pf.iter_batches(batch_size=a.batch_rows):
                table=pa.Table.from_batches([batch], schema=schema)
                writer.write_table(table)
                scenario_rows += table.num_rows
            expected_rows=int(m['scenarios'][scenario]['rows'])
            if scenario_rows!=expected_rows:
                raise SystemExit(f'{scenario}: streamed rows {scenario_rows} != manifest {expected_rows}')
            total += scenario_rows
            combined_scenarios[scenario]=m['scenarios'][scenario]
            archives.extend(m.get('archives',[]))
            pfraction=float(m.get('pilot_fraction'))
            if pilot_fraction is None: pilot_fraction=pfraction
            elif abs(pilot_fraction-pfraction)>1e-12:
                raise SystemExit('pilot_fraction differs across scenario manifests')
    finally:
        if writer is not None: writer.close()
    if total<=0 or not out.exists():
        raise SystemExit('combined parquet is empty/missing')
    combined={
        'source':'Microsoft Yatesbury / NetVigil benchmark',
        'archives':sorted(archives,key=lambda x:x['file']),
        'pilot_fraction':pilot_fraction,
        'processed_rows':total,
        'processed_sha256':sha256(out),
        'scenarios':combined_scenarios,
        'combination':'streamed concatenation of independently validated scenario parquet files',
    }
    mp=Path(a.manifest); mp.parent.mkdir(parents=True,exist_ok=True)
    mp.write_text(json.dumps(combined,indent=2),encoding='utf-8')
    pf=pq.ParquetFile(out)
    if pf.metadata.num_rows!=total:
        raise SystemExit(f'combined parquet metadata rows {pf.metadata.num_rows} != {total}')
    required={'ts','src_ip','dst_ip','src_port','dst_port','protocol','direction','decision','flow_state','packets_sent','bytes_sent','packets_received','bytes_received','attack_label','scenario','trace_offset_s','pilot_split'}
    missing=required-set(pf.schema_arrow.names)
    if missing: raise SystemExit(f'combined parquet missing columns: {sorted(missing)}')
    if int(combined_scenarios['normal_synflood_ddos']['attack_rows'])<=0:
        raise SystemExit('SYN-flood DDoS scenario has no positive labels according to validated source manifest')
    print(json.dumps({'status':'PASS','rows':total,'sha256':combined['processed_sha256'],'scenarios':expected},indent=2))

if __name__=='__main__': main()
