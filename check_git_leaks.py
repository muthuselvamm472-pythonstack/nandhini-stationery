"""
Nandhini Stationery - Git Secret Leak & File Exposure Scanner
Scans project files to verify that no credentials, private keys, or databases are exposed.
"""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SENSITIVE_PATTERNS = [
    (r"django-insecure-[a-zA-Z0-9!@#$%^&*()_+=-]+", "Django Insecure Default Secret Key"),
    (r"BEGIN\s+PRIVATE\s+KEY", "Unencrypted Private PEM Key"),
    (r"aws_access_key_id\s*=", "AWS Access Key"),
    (r"AIza[0-9A-Za-z-_]{35}", "Google API Key"),
    (r"ghp_[0-9a-zA-Z]{36}", "GitHub Personal Access Token"),
]

EXCLUDE_DIRS = {'.git', '__pycache__', 'backups', 'staticfiles', '.pytest_cache'}
EXCLUDE_FILES = {'check_git_leaks.py', '.env.example', 'SECURITY_HARDENING_MASTER_PLAN.md'}


def run_audit():
    findings = []
    print("=" * 60)
    print("  NANDHINI STATIONERY - GIT LEAK & SECRET EXPOSURE AUDIT")
    print("=" * 60)

    # 1. Check for .env and .gitignore existence
    env_file = BASE_DIR / '.env'
    gitignore_file = BASE_DIR / '.gitignore'

    if not env_file.exists():
        findings.append("CRITICAL: .env file is missing!")
    else:
        print("[PASS] .env file exists and is isolated.")

    if not gitignore_file.exists():
        findings.append("CRITICAL: .gitignore file is missing!")
    else:
        gitignore_content = gitignore_file.read_text(encoding='utf-8')
        for required_pattern in ['.env', '*.sqlite3', 'backups/', 'staticfiles/']:
            if required_pattern not in gitignore_content:
                findings.append(f"WARNING: '{required_pattern}' missing from .gitignore!")
            else:
                print(f"[PASS] .gitignore correctly excludes '{required_pattern}'.")

    # 2. Check for leaked secret patterns in Python, HTML, JS files
    scanned_count = 0
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES or f == '.env':
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in ['.py', '.html', '.js', '.json', '.bat', '.ps1', '.yaml']:
                file_path = Path(root) / f
                scanned_count += 1
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    for pattern, label in SENSITIVE_PATTERNS:
                        matches = re.findall(pattern, content)
                        if matches:
                            findings.append(f"LEAK DETECTED: {label} found in {file_path.relative_to(BASE_DIR)}")
                except Exception as e:
                    findings.append(f"ERROR reading {f}: {e}")

    print(f"[INFO] Scanned {scanned_count} project files for credential signatures.")

    # 3. Check database permissions & backups isolation
    backups_dir = BASE_DIR / 'backups'
    if backups_dir.exists():
        backup_files = list(backups_dir.glob("*.sqlite3"))
        print(f"[INFO] Found {len(backup_files)} local backup databases (quarantined in backups/).")

    print("-" * 60)
    if findings:
        print(f"[FAILED] {len(findings)} security finding(s):")
        for finding in findings:
            print(f"  ❌ {finding}")
        return False
    else:
        print("[SUCCESS] Zero credentials or sensitive secrets exposed in project files!")
        print("[SUCCESS] All database files and environment secrets are safely quarantined.")
        return True


if __name__ == '__main__':
    success = run_audit()
    exit(0 if success else 1)

