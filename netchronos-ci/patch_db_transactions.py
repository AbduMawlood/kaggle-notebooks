#!/usr/bin/env python3
"""Fail-closed Psycopg 3 transaction-boundary patch for NetChronos DDL helpers.

The checksum-pinned research bundle is left unchanged on disk in Git history. At CI
runtime this compatibility patch fixes a real reconfiguration bug exposed by the
TimescaleDB 2.29.1 semantic gate: state-inspection SELECTs leave a Psycopg connection
INTRANS, after which the DDL helper cannot switch to autocommit for operations such as
CREATE INDEX CONCURRENTLY.

Semantics:
- IDLE: enter autocommit normally.
- INTRANS: explicitly commit the completed inspection transaction, then enter autocommit.
- INERROR: rollback the failed transaction, then enter autocommit.
- ACTIVE/UNKNOWN/other: fail closed instead of guessing.

This changes transaction plumbing only. It does not alter any candidate, SLO, workload,
query, physical-design decision, random seed, or measurement definition.
"""
from pathlib import Path

path = Path('src/netchronos/db.py')
s = path.read_text(encoding='utf-8')

old = '''def execute_statements(conn, statements: Iterable[str]) -> None:\n    old=conn.autocommit; conn.autocommit=True\n    try:\n        with conn.cursor() as cur:\n            for s in statements:\n                if s.strip(): cur.execute(s)\n    finally:\n        conn.autocommit=old\n'''
new = '''def execute_statements(conn, statements: Iterable[str]) -> None:\n    # Psycopg 3 does not allow changing autocommit while a connection is INTRANS.\n    # Physical-state inspection SELECTs immediately before DDL legitimately leave a\n    # read-only transaction open, so close that transaction explicitly. Fail closed\n    # for ACTIVE/UNKNOWN states rather than silently committing ambiguous work.\n    old = conn.autocommit\n    if not old:\n        status = conn.info.transaction_status\n        if status == psycopg.pq.TransactionStatus.INTRANS:\n            conn.commit()\n        elif status == psycopg.pq.TransactionStatus.INERROR:\n            conn.rollback()\n        elif status != psycopg.pq.TransactionStatus.IDLE:\n            raise RuntimeError(f"Cannot enter DDL autocommit from transaction state {status!r}")\n    conn.autocommit = True\n    try:\n        with conn.cursor() as cur:\n            for s in statements:\n                if s.strip():\n                    cur.execute(s)\n    finally:\n        conn.autocommit = old\n'''

count = s.count(old)
if count != 1:
    raise SystemExit(f'{path}: expected exactly one execute_statements target, found {count}')
s = s.replace(old, new, 1)

required = [
    'psycopg.pq.TransactionStatus.INTRANS',
    'psycopg.pq.TransactionStatus.INERROR',
    'Cannot enter DDL autocommit from transaction state',
]
for token in required:
    if token not in s:
        raise SystemExit(f'{path}: transaction patch verification failed: {token}')
path.write_text(s, encoding='utf-8')
print(f'patched {path}: explicit Psycopg transaction boundary before DDL autocommit')
