#!/usr/bin/env python3
"""
tools/backup_db.py — Daily Online SQLite Backup for GMS

Performs an atomic, non-blocking online backup using SQLite's native backup API.
Overwrites a single canonical backup file (gms_trust.sqlite.bak) to guarantee
zero disk bloat and 100% transactional consistency even during active WAL writes.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories"))


def backup_database(
    mem_root: Path | None = None,
    dest_path: Path | None = None,
) -> dict:
    root = Path(mem_root) if mem_root else DEFAULT_MEM_ROOT
    src_db = root / "gms_trust.sqlite"
    dst_db = Path(dest_path) if dest_path else root / "gms_trust.sqlite.bak"

    if not src_db.exists():
        return {"status": "error", "message": f"Source DB does not exist: {src_db}"}

    dst_db.parent.mkdir(parents=True, exist_ok=True)

    # Use SQLite Online Backup API
    src_conn = sqlite3.connect(str(src_db))
    dst_conn = sqlite3.connect(str(dst_db))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    # Integrity verification
    verify_conn = sqlite3.connect(str(dst_db))
    cursor = verify_conn.cursor()
    cursor.execute("PRAGMA integrity_check")
    check_result = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
    table_count = cursor.fetchone()[0]
    verify_conn.close()

    size_bytes = dst_db.stat().st_size
    now_iso = datetime.now().isoformat()

    return {
        "status": "success" if check_result == "ok" else "corrupt",
        "timestamp": now_iso,
        "source": str(src_db),
        "destination": str(dst_db),
        "size_bytes": size_bytes,
        "table_count": table_count,
        "integrity": check_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup GMS SQLite database.")
    parser.add_argument("--root", default=None, help="Custom memory root directory.")
    parser.add_argument("--dest", default=None, help="Custom destination file path.")
    parser.add_argument("--json", action="store_true", help="Output report as JSON.")
    args = parser.parse_args()

    mem_root = Path(args.root).resolve() if args.root else None
    dest_path = Path(args.dest).resolve() if args.dest else None
    report = backup_database(mem_root=mem_root, dest_path=dest_path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = report["status"].upper()
        if report["status"] == "success":
            print(f"[{report['timestamp']}] GMS DB Backup: {status} -> {report['destination']} ({report['size_bytes']} bytes, {report['table_count']} tables, integrity: {report['integrity']})")
        else:
            print(f"[{datetime.now().isoformat()}] GMS DB Backup FAILED: {report.get('message', 'Unknown error')}")

    return 0 if report.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
