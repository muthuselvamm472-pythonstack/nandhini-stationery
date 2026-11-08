"""
Automated Database Backup Utility for Nandhini Stationery
Safely creates timestamped snapshots of SQLite in WAL mode without downtime.
Retains the latest 15 backups in the 'backups/' directory.
"""
import os
import sys
import time
import sqlite3
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite3"
BACKUPS_DIR = BASE_DIR / "backups"


def perform_db_backup(keep_latest: int = 15) -> str:
    """
    Performs an online, zero-downtime backup of SQLite database using SQLite's native backup API.
    Works seamlessly with concurrent readers and writers in WAL mode.
    """
    if not DB_PATH.exists():
        print(f"[ERROR] Database file not found at: {DB_PATH}", file=sys.stderr)
        return ""

    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"db_backup_{timestamp}.sqlite3"
    backup_file_path = BACKUPS_DIR / backup_filename

    # SQLite online backup API
    source_conn = None
    target_conn = None
    try:
        source_conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
        target_conn = sqlite3.connect(str(backup_file_path))

        # Online Database Integrity Verification
        cursor = source_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        integrity = cursor.fetchone()
        if not integrity or integrity[0] != "ok":
            print(f"[ALERT] Database integrity anomaly detected: {integrity}", file=sys.stderr)
        else:
            print("[HEALTH] SQLite Database Integrity Verified: OK (0 errors)", flush=True)

        # Perform online page-by-page replication
        source_conn.backup(target_conn, pages=100, sleep=0.01)

        size_kb = backup_file_path.stat().st_size / 1024
        print(f"[OK] Database backup created: {backup_filename} ({size_kb:.1f} KB)", flush=True)

        # Prune old backups, retaining the most recent keep_latest
        existing_backups = sorted(
            BACKUPS_DIR.glob("db_backup_*.sqlite3"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if len(existing_backups) > keep_latest:
            for old_file in existing_backups[keep_latest:]:
                try:
                    old_file.unlink()
                    print(f"[PRUNE] Removed older backup: {old_file.name}", flush=True)
                except Exception as e:
                    print(f"[WARN] Could not remove {old_file.name}: {e}", file=sys.stderr)

        return str(backup_file_path)

    except Exception as exc:
        print(f"[ERROR] Failed to backup database: {exc}", file=sys.stderr)
        return ""
    finally:
        if target_conn:
            target_conn.close()
        if source_conn:
            source_conn.close()


if __name__ == "__main__":
    result = perform_db_backup()
    if result:
        print(f"[SUCCESS] Backup saved to {result}")
        sys.exit(0)
    else:
        sys.exit(1)
