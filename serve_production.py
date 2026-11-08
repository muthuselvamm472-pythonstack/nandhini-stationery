"""
Nandhini Stationery - High-Concurrency Production WSGI Server
Powered by Waitress with 16 multi-threaded workers, channel timeouts,
SQLite WAL concurrency, and automated bot shields.
"""
import os
import sys
import django
from pathlib import Path

# Safe Unicode output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nandhini_stationery.settings')
django.setup()

from nandhini_stationery.wsgi import application
from waitress import serve
from backup_db import perform_db_backup
import threading
import time

def schedule_periodic_backups():
    """Runs a database backup in the background every 12 hours"""
    while True:
        time.sleep(12 * 3600)
        try:
            perform_db_backup(keep_latest=15)
        except Exception:
            pass

# Perform immediate startup backup
startup_backup = perform_db_backup(keep_latest=15)

backup_thread = threading.Thread(target=schedule_periodic_backups, daemon=True, name="DBBackupScheduler")
backup_thread.start()

HOST = "0.0.0.0"
PORT = 8000
THREADS = 16

banner = f"""
======================================================================
       NANDHINI STATIONERY - HIGH-CONCURRENCY PRODUCTION SERVER
======================================================================
 Server Engine:   Waitress WSGI (Multi-Threaded Production Runner)
 Worker Threads:  {THREADS} Concurrent Connections (Zero Freeze)
 Database Engine: SQLite WAL Mode + 5000ms Busy Timeout
 Bot Shield:      Active (Rate Limiting, Honeypot, Scanner Defense)
 Local URL:       http://127.0.0.1:{PORT}/
 Network URL:     http://0.0.0.0:{PORT}/ (Accessible via Shop Wi-Fi)
 Admin Portal:    http://127.0.0.1:{PORT}/nandhini-admin/
 Customer Portal: http://127.0.0.1:{PORT}/dashboard/
======================================================================
 Server is ONLINE. Press Ctrl+C to stop.
"""
print(banner, flush=True)

try:
    serve(
        application,
        host=HOST,
        port=PORT,
        threads=THREADS,
        channel_timeout=60,
        cleanup_interval=30,
        connection_limit=500,
        backlog=100,
        asyncore_use_poll=True,
        ident=None
    )
except KeyboardInterrupt:
    print("\n[OK] Server stopped cleanly.", flush=True)
