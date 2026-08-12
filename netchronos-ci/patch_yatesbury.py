#!/usr/bin/env python3
"""Patch the frozen preparer for Yatesbury archives that omit CSV header rows.

The patch does not alter source records. It first accepts Microsoft-published headers
when present; otherwise it assigns Microsoft's documented field order to headerless
records and retains the preparer's strict schema checks.
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
if "df=read_yatesbury_csv(nsg, list(COLS))" not in s:
    raise SystemExit('nsg parser replacement failed')
if "lab=read_yatesbury_csv(label_path" not in s:
    raise SystemExit('label parser replacement failed')
path.write_text(s, encoding='utf-8')
print(f'patched {path} for headered/headerless Yatesbury CSV compatibility')
