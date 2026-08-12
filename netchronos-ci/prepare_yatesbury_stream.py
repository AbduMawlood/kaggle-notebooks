#!/usr/bin/env python3
"""Memory-bounded preparation of one Microsoft Yatesbury scenario.

This is a streaming implementation of the frozen prepare_yatesbury.py semantics.
No source flow values are synthesized or subsampled. Label attachment remains an
IP-pair-constrained, backward 2-minute as-of join to the authoritative label.csv.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, pathlib, tarfile
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

COLS = {
    'time':'ts','Source IP':'src_ip','Destination IP':'dst_ip','Source port':'src_port',
    'Destination port':'dst_port','Protocol':'protocol','Traffic flow':'direction',
    'Traffic decision':'decision','Flow State':'flow_state','Packets sent':'packets_sent',
    'Bytes sent':'bytes_sent','Packets received':'packets_received','Bytes received':'bytes_received'
}
PROTO={'T':6,'U':17}
LABEL_COLS=['Source IP','Destination IP','time','label']

def sha256(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def csv_layout(path:pathlib.Path, expected):
    with path.open('r',encoding='utf-8',errors='strict',newline='') as fh: sample=fh.read(16384)
    if not sample: raise ValueError(f'{path}: empty CSV')
    try: sep=csv.Sniffer().sniff(sample,delimiters=',\t|;').delimiter
    except csv.Error as exc: raise ValueError(f'{path}: unable to determine delimiter') from exc
    first=next(csv.reader([sample.splitlines()[0]],delimiter=sep))
    header=set(expected).issubset(set(first))
    return sep,header

def read_label(path:pathlib.Path)->pd.DataFrame:
    if not path.exists(): return pd.DataFrame(columns=['src_ip','dst_ip','label_start','attack_label'])
    sep,header=csv_layout(path,LABEL_COLS)
    lab=pd.read_csv(path,sep=sep,header=0 if header else None,names=None if header else LABEL_COLS)
    req=set(LABEL_COLS)
    if not req.issubset(lab.columns): raise ValueError(f'{path}: expected label columns {sorted(req)}')
    lab=lab[LABEL_COLS].rename(columns={'Source IP':'src_ip','Destination IP':'dst_ip','time':'label_start','label':'attack_label'})
    lab['label_start']=pd.to_datetime(lab['label_start'],utc=True,errors='raise').astype('datetime64[ns, UTC]')
    lab['attack_label']=pd.to_numeric(lab['attack_label'],errors='raise').astype('int8')
    return lab.sort_values(['label_start','src_ip','dst_ip']).reset_index(drop=True)

def nsg_reader(path:pathlib.Path,chunksize:int,usecols=None):
    expected=list(COLS)
    sep,header=csv_layout(path,expected)
    kw=dict(sep=sep,chunksize=chunksize,header=0 if header else None,names=None if header else expected)
    if usecols is not None: kw['usecols']=usecols
    return pd.read_csv(path,**kw)

def transform_chunk(df:pd.DataFrame,lab:pd.DataFrame,scenario:str,t0,pilot_cutoff):
    missing=set(COLS)-set(df.columns)
    if missing: raise ValueError(f'missing NSG columns: {sorted(missing)}')
    x=df[list(COLS)].rename(columns=COLS)
    x['ts']=pd.to_datetime(x['ts'],utc=True,errors='raise').astype('datetime64[ns, UTC]')
    x['protocol']=x['protocol'].map(PROTO).fillna(-1).astype('int16')
    for c in ['src_port','dst_port','packets_sent','bytes_sent','packets_received','bytes_received']:
        x[c]=pd.to_numeric(x[c],errors='coerce').fillna(0).astype('int64')
    if lab.empty:
        x['attack_label']=pd.Series(0,index=x.index,dtype='int8')
    else:
        ev=x.sort_values(['ts','src_ip','dst_ip']).copy()
        y=pd.merge_asof(
            ev,lab[['src_ip','dst_ip','label_start','attack_label']],
            left_on='ts',right_on='label_start',by=['src_ip','dst_ip'],
            direction='backward',tolerance=pd.Timedelta(minutes=2)
        )
        y['attack_label']=y['attack_label'].fillna(0).astype('int8')
        x=y.drop(columns=['label_start'])
    x['scenario']=scenario
    x=x.sort_values('ts').reset_index(drop=True)
    x['trace_offset_s']=(x['ts']-t0).dt.total_seconds().astype('float64')
    x['pilot_split']=x['ts'].le(pilot_cutoff)
    return x

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--raw',default='data/raw/yatesbury')
    p.add_argument('--scenario',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--manifest',required=True)
    p.add_argument('--pilot-fraction',type=float,default=0.20)
    p.add_argument('--chunksize',type=int,default=200000)
    a=p.parse_args()
    if not (0<a.pilot_fraction<0.5): raise SystemExit('--pilot-fraction must be between 0 and 0.5')
    raw=pathlib.Path(a.raw); tgz=raw/f'{a.scenario}.tar.gz'
    if not tgz.exists(): raise SystemExit(f'{tgz} missing')
    archive={'file':tgz.name,'sha256':sha256(tgz),'bytes':tgz.stat().st_size}
    work=raw/'extracted'; target=work/a.scenario; target.mkdir(parents=True,exist_ok=True)
    if not list(target.rglob('nsg.csv')):
        with tarfile.open(tgz) as tf: tf.extractall(target,filter='data')
    nsgs=list(target.rglob('nsg.csv'))
    if len(nsgs)!=1: raise SystemExit(f'{a.scenario}: expected one nsg.csv, found {len(nsgs)}')
    nsg=nsgs[0]; label=nsg.with_name('label.csv')

    # First bounded pass computes the exact chronological split boundary.
    t0=t1=None; rows_scan=0
    for chunk in nsg_reader(nsg,a.chunksize,usecols=['time']):
        ts=pd.to_datetime(chunk['time'],utc=True,errors='raise').astype('datetime64[ns, UTC]')
        if ts.empty: continue
        lo,hi=ts.min(),ts.max(); rows_scan+=len(ts)
        t0=lo if t0 is None or lo<t0 else t0; t1=hi if t1 is None or hi>t1 else t1
    if t0 is None or t1 is None or rows_scan<=0: raise SystemExit(f'{a.scenario}: no NSG rows')
    cutoff=t0+(t1-t0)*a.pilot_fraction
    lab=read_label(label)

    out=pathlib.Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    writer=None; schema=None; total=attack_rows=0; unique_src=set(); unique_dst=set()
    try:
        for raw_chunk in nsg_reader(nsg,a.chunksize):
            x=transform_chunk(raw_chunk,lab,a.scenario,t0,cutoff)
            unique_src.update(x['src_ip'].dropna().astype(str).unique().tolist())
            unique_dst.update(x['dst_ip'].dropna().astype(str).unique().tolist())
            total+=len(x); attack_rows+=int(x['attack_label'].sum())
            table=pa.Table.from_pandas(x,preserve_index=False)
            if writer is None:
                schema=table.schema; writer=pq.ParquetWriter(out,schema,compression='snappy')
            elif not table.schema.equals(schema,check_metadata=False):
                table=table.cast(schema)
            writer.write_table(table,row_group_size=min(a.chunksize,250000))
    finally:
        if writer is not None: writer.close()
    if total!=rows_scan: raise SystemExit(f'{a.scenario}: output rows {total} != scanned source rows {rows_scan}')
    if not out.exists() or pq.ParquetFile(out).metadata.num_rows!=total: raise SystemExit(f'{a.scenario}: parquet row count mismatch')
    manifest={
        'source':'Microsoft Yatesbury / NetVigil benchmark','archives':[archive],
        'pilot_fraction':a.pilot_fraction,'processed_rows':total,'processed_sha256':sha256(out),
        'scenarios':{a.scenario:{'rows':total,'start':t0.isoformat(),'end':t1.isoformat(),'attack_rows':attack_rows,'unique_src':len(unique_src),'unique_dst':len(unique_dst)}},
        'preparation':'memory-bounded streaming implementation of frozen Yatesbury transformations'
    }
    mp=pathlib.Path(a.manifest); mp.parent.mkdir(parents=True,exist_ok=True); mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','scenario':a.scenario,'rows':total,'attack_rows':attack_rows,'sha256':manifest['processed_sha256']},indent=2))
if __name__=='__main__': main()
