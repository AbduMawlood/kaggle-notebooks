#!/usr/bin/env python3
"""Patch the frozen preparer for Yatesbury archive compatibility.

The patch does not alter source records. It:
1. accepts Microsoft-published headers when present;
2. assigns Microsoft's documented field order only when archives omit CSV headers; and
3. normalizes event and label timestamps to the same UTC nanosecond dtype before
   pandas.merge_asof, avoiding pandas 3.x resolution mismatches (us vs ns).
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
    # Yatesbury release archives are not uniform about carrying a header row.
    # Delimiter inference is retained, and Microsoft's documented column order is
    # applied only if the expected header names are absent.
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
# pandas 3.x may preserve different inferred datetime units for different files.
# merge_asof requires the join dtypes to match exactly, so normalize both to ns UTC.
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
checks = [
    "df=read_yatesbury_csv(nsg, list(COLS))",
    "lab=read_yatesbury_csv(label_path",
    "datetime64[ns, UTC]",
]
for check in checks:
    if check not in s:
        raise SystemExit(f'patch verification failed: {check}')
path.write_text(s, encoding='utf-8')
print(f'patched {path} for Yatesbury CSV compatibility and UTC-ns timestamp normalization')
