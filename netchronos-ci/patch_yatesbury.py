#!/usr/bin/env python3
"""Patch the frozen Yatesbury preparer for release/pandas compatibility.

The patch preserves source records and benchmark semantics. It:
1. accepts Microsoft-published headers when present;
2. assigns Microsoft's documented field order only when archives omit CSV headers;
3. normalizes event and label timestamps to the same UTC nanosecond dtype; and
4. replaces the per-IP-pair Python merge loop with one vectorized merge_asof using
   the same pair keys, backward direction and 2-minute tolerance.
Strict schema checks remain active.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else 'scripts/prepare_yatesbury.py')
s = path.read_text(encoding='utf-8')

marker = "PROTO={'T':6,'U':17}\n"
helper = r'''PROTO={'T':6,'U':17}


def read_yatesbury_csv(path, expected):
    expected = list(expected)
    df = pd.read_csv(path, sep=None, engine='python')
    if set(expected).issubset(set(df.columns)):
        return df
    df = pd.read_csv(path, sep=None, engine='python', header=None, names=expected)
    if df.shape[1] != len(expected):
        raise ValueError(f"{path}: expected {len(expected)} fields, parsed {df.shape[1]}")
    return df
'''
if marker not in s:
    raise SystemExit('PROTO marker not found; refusing to patch an unexpected preparer')
s = s.replace(marker, helper, 1)
s = s.replace(
    "lab=pd.read_csv(label_path)",
    "lab=read_yatesbury_csv(label_path, ['Source IP','Destination IP','time','label'])",
    1,
)
s = s.replace(
    "df=pd.read_csv(nsg)",
    "df=read_yatesbury_csv(nsg, list(COLS))",
    1,
)
# pandas 3.x can retain different inferred units for timestamps from different files.
s = s.replace(
    "lab['label_start']=pd.to_datetime(lab['label_start'],utc=True,errors='raise')",
    "lab['label_start']=pd.to_datetime(lab['label_start'],utc=True,errors='raise').astype('datetime64[ns, UTC]')",
    1,
)
s = s.replace(
    "x['ts']=pd.to_datetime(x['ts'],utc=True,errors='raise')",
    "x['ts']=pd.to_datetime(x['ts'],utc=True,errors='raise').astype('datetime64[ns, UTC]')",
    1,
)

old_join = r'''    # merge_asof is applied per pair to correctly honor the dataset's 2-minute windows
    # even if window starts are not aligned to an assumed clock boundary.
    pieces=[]
    labels_by_pair={k:g.sort_values('label_start') for k,g in lab.groupby(['src_ip','dst_ip'],sort=False)}
    for pair,g in events.groupby(['src_ip','dst_ip'],sort=False):
        lg=labels_by_pair.get(pair)
        if lg is None or lg.empty:
            y=g.copy(); y['attack_label']=0; pieces.append(y); continue
        y=pd.merge_asof(
            g.sort_values('ts'), lg[['label_start','attack_label']].sort_values('label_start'),
            left_on='ts', right_on='label_start', direction='backward',
            tolerance=pd.Timedelta(minutes=2),
        )
        y['attack_label']=y['attack_label'].fillna(0).astype('int8')
        y=y.drop(columns=['label_start'])
        pieces.append(y)
    return pd.concat(pieces,ignore_index=True)
'''
new_join = r'''    # Vectorized equivalent of the original per-pair loop. merge_asof still joins
    # only within the same source/destination pair, backward in time, with the
    # authoritative 2-minute label-window tolerance. Global time sorting satisfies
    # pandas' asof ordering requirement and avoids thousands of Python-level merges.
    ev = events.sort_values(['ts','src_ip','dst_ip']).copy()
    lb = lab.sort_values(['label_start','src_ip','dst_ip']).copy()
    y = pd.merge_asof(
        ev,
        lb[['src_ip','dst_ip','label_start','attack_label']],
        left_on='ts', right_on='label_start',
        by=['src_ip','dst_ip'],
        direction='backward',
        tolerance=pd.Timedelta(minutes=2),
    )
    y['attack_label']=y['attack_label'].fillna(0).astype('int8')
    return y.drop(columns=['label_start']).reset_index(drop=True)
'''
if old_join not in s:
    raise SystemExit('original label-join block not found; refusing unsafe patch')
s = s.replace(old_join, new_join, 1)

checks = [
    "df=read_yatesbury_csv(nsg, list(COLS))",
    "lab=read_yatesbury_csv(label_path",
    "datetime64[ns, UTC]",
    "by=['src_ip','dst_ip']",
]
for check in checks:
    if check not in s:
        raise SystemExit(f'patch verification failed: {check}')
path.write_text(s, encoding='utf-8')
print(f'patched {path}: CSV/header compatibility, UTC-ns timestamps, vectorized label join')
