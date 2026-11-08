"""
Nandhini Stationery - One-Click Server & Dashboard Launcher
Starts the Django server (if not already running) and opens both
Admin and Customer Dashboards in the default web browser.
"""
import os
import sys
import time
import socket
import webbrowser
import subprocess
from pathlib import Path

# Safe Unicode output on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg="", **kwargs):
    print(msg, flush=True, **kwargs)


HOST = "127.0.0.1"
PORT = 8000
SERVER_URL = f"http://{HOST}:{PORT}/"
ADMIN_URL = f"http://{HOST}:{PORT}/nandhini-admin/"
CUSTOMER_URL = f"http://{HOST}:{PORT}/dashboard/"
CUSTOMER_LOGIN_URL = f"http://{HOST}:{PORT}/login/"


def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0


def wait_for_server(host: str, port: int, timeout_sec: int = 15) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if is_port_in_use(host, port):
            time.sleep(0.5)
            return True
        time.sleep(0.5)
    return False


def open_dashboards():
    log("\n[+] Opening Dashboards in your default web browser...")
    try:
        webbrowser.open(ADMIN_URL)
        time.sleep(0.6)
        webbrowser.open(CUSTOMER_URL)
        log("    [OK] Admin and Customer dashboards opened in browser tabs.")
    except Exception as e:
        log(f"    [!] Note: Could not auto-open browser: {e}")
        log("        Please open the URLs manually.")


def print_banner():
    banner = f"""
======================================================================
           NANDHINI STATIONERY - DASHBOARD CONTROLLER
======================================================================
 Server Status:   ONLINE ({SERVER_URL})

 [1] Customer Dashboard:
     URL:          {CUSTOMER_URL}
     Direct Login: {CUSTOMER_LOGIN_URL}
     Test Phones:  9856278642 (Muthu selvam)
                   8678922362 (selva_2005)
                   9876543210 (Nandhini)
     (No password or PIN required - instant phone login)

 [2] Owner Admin Dashboard:
     URL:          {ADMIN_URL}
     Django Admin: http://{HOST}:{PORT}/admin/
     Username:     admin (Use your configured secure password)
======================================================================
"""
    log(banner)


def main():
    base_dir = Path(__file__).resolve().parent
    os.chdir(base_dir)

    log("Checking local server status on port 8000...")
    server_already_running = is_port_in_use(HOST, PORT)

    if server_already_running:
        log(f" [OK] Django server is already active on http://{HOST}:{PORT}/")
        print_banner()
        open_dashboards()
        log("\nDashboards opened! Press Ctrl+C or close this window when done.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log("\nDashboard launcher exited. (Background server remains active).")
            return
        prod_script = base_dir / "serve_production.py"
        if prod_script.exists():
            log(f" Starting High-Concurrency Production Server (Waitress WSGI, 16 Threads)...")
            cmd = [sys.executable, str(prod_script)]
        else:
            log(f" Starting Django server at http://{HOST}:{PORT}/ ...")
            cmd = [sys.executable, "manage.py", "runserver", f"0.0.0.0:{PORT}"]

        try:
            proc = subprocess.Popen(cmd, cwd=str(base_dir))
        except Exception as e:
            log(f"[ERROR] Failed to start Django server: {e}")
            sys.exit(1)

        if wait_for_server(HOST, PORT, timeout_sec=15):
            log(f" [OK] Server successfully started!")
            print_banner()
            open_dashboards()
            log("\nServer is running. Press Ctrl+C in this window to stop the server.\n")
            try:
                proc.wait()
            except KeyboardInterrupt:
                log("\nStopping Django server...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log(" [OK] Server stopped cleanly.")
        else:
            log("\n [!] Server did not respond within 15 seconds.")
            if proc.poll() is not None:
                log(f"     Server process exited with code {proc.returncode}")
            else:
                proc.terminate()
            sys.exit(1)


if __name__ == "__main__":
    main()
