#!/usr/bin/env python3
"""Fail-closed Psycopg 3 transaction-boundary patch for NetChronos DDL helpers.

The checksum-pinned research bundle is left unchanged in Git. At CI runtime this fixes
a reconfiguration bug exposed by TimescaleDB 2.29.1: state-inspection SELECTs leave a
Psycopg connection INTRANS, after which the DDL helper cannot switch to autocommit for
operations such as CREATE INDEX CONCURRENTLY.

Semantics:
- IDLE: enter autocommit normally.
- INTRANS: explicitly commit the completed inspection transaction, then enter autocommit.
- INERROR: rollback the failed transaction, then enter autocommit.
- ACTIVE/UNKNOWN/other: fail closed instead of guessing.

This changes transaction plumbing only. It does not alter candidates, SLOs, workload,
queries, physical-design decisions, random seeds, or measurement definitions.
"""
from pathlib import Path

path = Path('src/netchronos/db.py')
s = path.read_text(encoding='utf-8')

old = '''def execute_statements(conn, statements: Iterable[str]) -> None:\n    """Execute DDL with autocommit so CONCURRENTLY is legal and timings are real."""\n    previous = conn.autocommit\n    conn.autocommit = True\n    try:\n        with conn.cursor() as cur:\n            for statement in statements:\n                cur.execute(statement)\n    finally:\n        conn.autocommit = previous\n'''
new = '''def execute_statements(conn, statements: Iterable[str]) -> None:\n    """Execute DDL with an explicit, fail-closed autocommit boundary.\n\n    Psycopg 3 forbids changing ``autocommit`` while the connection is INTRANS.\n    NetChronos legitimately performs read-only physical-state inspection immediately\n    before DDL, so that completed inspection transaction is committed explicitly.\n    Failed transactions are rolled back; ambiguous ACTIVE/UNKNOWN states are rejected.\n    """\n    previous = conn.autocommit\n    if not previous:\n        status = conn.info.transaction_status\n        if status == psycopg.pq.TransactionStatus.INTRANS:\n            conn.commit()\n        elif status == psycopg.pq.TransactionStatus.INERROR:\n            conn.rollback()\n        elif status != psycopg.pq.TransactionStatus.IDLE:\n            raise RuntimeError(f"Cannot enter DDL autocommit from transaction state {status!r}")\n    conn.autocommit = True\n    try:\n        with conn.cursor() as cur:\n            for statement in statements:\n                cur.execute(statement)\n    finally:\n        conn.autocommit = previous\n'''

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
