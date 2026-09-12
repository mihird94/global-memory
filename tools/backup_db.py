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


def restore_database(
    mem_root: Path | None = None,
    backup_path: Path | None = None,
    dest_path: Path | None = None,
) -> dict:
    """
    Restore GMS SQLite database from canonical backup (.bak).
    Verifies backup integrity before restoring to prevent propagating corruption.
    """
    root = Path(mem_root) if mem_root else DEFAULT_MEM_ROOT
    bak_db = Path(backup_path) if backup_path else root / "gms_trust.sqlite.bak"
    target_db = Path(dest_path) if dest_path else root / "gms_trust.sqlite"

    if not bak_db.exists():
        return {"status": "error", "message": f"Backup file does not exist: {bak_db}"}

    # Verify backup integrity first
    try:
        verify_conn = sqlite3.connect(str(bak_db))
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        check_result = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        verify_conn.close()
        if check_result != "ok":
            return {"status": "error", "message": f"Backup file failed integrity check: {check_result}"}
    except Exception as e:
        return {"status": "error", "message": f"Cannot read backup database: {e}"}

    # Ensure target destination is clear of corrupted files before restoring
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()
    wal = target_db.with_name(target_db.name + "-wal")
    shm = target_db.with_name(target_db.name + "-shm")
    if wal.exists():
        wal.unlink()
    if shm.exists():
        shm.unlink()

    src_conn = sqlite3.connect(str(bak_db))
    dst_conn = sqlite3.connect(str(target_db))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    size_bytes = target_db.stat().st_size
    now_iso = datetime.now().isoformat()
    return {
        "status": "success",
        "timestamp": now_iso,
        "source": str(bak_db),
        "destination": str(target_db),
        "size_bytes": size_bytes,
        "table_count": table_count,
        "integrity": check_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup or restore GMS SQLite database.")
    parser.add_argument("--root", default=None, help="Custom memory root directory.")
    parser.add_argument("--dest", default=None, help="Custom destination file path.")
    parser.add_argument("--restore", action="store_true", help="Restore database from backup instead of backing up.")
    parser.add_argument("--backup-src", default=None, help="Custom source backup file path for restore.")
    parser.add_argument("--json", action="store_true", help="Output report as JSON.")
    args = parser.parse_args()

    mem_root = Path(args.root).resolve() if args.root else None
    dest_path = Path(args.dest).resolve() if args.dest else None

    if args.restore:
        backup_path = Path(args.backup_src).resolve() if args.backup_src else None
        report = restore_database(mem_root=mem_root, backup_path=backup_path, dest_path=dest_path)
        op_label = "GMS DB Restore"
    else:
        report = backup_database(mem_root=mem_root, dest_path=dest_path)
        op_label = "GMS DB Backup"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = report["status"].upper()
        if report["status"] == "success":
            print(f"[{report['timestamp']}] {op_label}: {status} -> {report['destination']} ({report['size_bytes']} bytes, {report['table_count']} tables, integrity: {report['integrity']})")
        else:
            print(f"[{datetime.now().isoformat()}] {op_label} FAILED: {report.get('message', 'Unknown error')}")

    return 0 if report.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
