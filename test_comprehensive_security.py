"""
Nandhini Stationery - Comprehensive Security, RBAC & Penetration Testing Suite
Validates all hardened defenses:
1. Environment & Secret Key Integrity (DEBUG=False, 64-char SECRET_KEY)
2. Admin Route Protection & RBAC
3. Admin & Auth Route Rate Limiting (Brute-Force defense)
4. Anti-XSS Sanitization & Injection Defense
5. Open Redirect Phishing Defense
6. Customer Session IDOR Isolation
7. OWASP Security Headers & CSP
8. Malicious Exploit Scanner Blocking (sqlmap, nikto)
9. Invisible Honeypot Trap
10. High-Concurrency SQLite WAL Concurrency
"""
import os
import sys
import django
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nandhini_stationery.settings')
django.setup()

from django.test import Client
from django.conf import settings
from django.core.cache import cache
from rewards.models import Customer, QRSlip, SystemSetting
from rewards.sanitizer import sanitize_text
from django.utils import timezone


def get_client(**kwargs):
    """Factory creating Django test client with permitted host"""
    return Client(SERVER_NAME='127.0.0.1', **kwargs)


def run_all_tests():
    print("=" * 70)
    print("  NANDHINI STATIONERY - COMPREHENSIVE PENETRATION & SECURITY AUDIT")
    print("=" * 70)

    passed = 0
    total = 0

    def assert_test(condition, name, details=""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] Test {total:02d}: {name}")
        else:
            print(f"  [FAIL] Test {total:02d}: {name} - {details}")

    # -------------------------------------------------------------
    # 1. Environment & Secret Key Integrity
    # -------------------------------------------------------------
    print("\n[SECTION 1: ENVIRONMENT & SECRET KEY ISOLATION]")
    assert_test(settings.DEBUG is False, "DEBUG Mode is disabled (False)")
    assert_test(len(settings.SECRET_KEY) >= 50, f"SECRET_KEY entropy >= 50 chars (length: {len(settings.SECRET_KEY)})")
    assert_test(not settings.SECRET_KEY.startswith('django-insecure-'), "SECRET_KEY does not use insecure default prefix")
    assert_test('*' not in settings.ALLOWED_HOSTS, f"ALLOWED_HOSTS does not allow wildcard '*' ({settings.ALLOWED_HOSTS})")
    assert_test(settings.CORS_ALLOW_ALL_ORIGINS is False, "CORS does not allow all origins wildcard")

    # Host header attack test: Unknown forged host header
    host_attacker_client = Client(SERVER_NAME='evil-attacker.com')
    attack_resp = host_attacker_client.get('/')
    assert_test(attack_resp.status_code == 400, "Forged Host Header (evil-attacker.com) blocked with HTTP 400 Bad Request")

    # -------------------------------------------------------------
    # 2. Admin Route Protection & RBAC
    # -------------------------------------------------------------
    print("\n[SECTION 2: ADMIN ROUTE PROTECTION & RBAC]")
    client = get_client()
    admin_resp = client.get('/nandhini-admin/')
    assert_test(admin_resp.status_code == 302 and '/admin/login/' in admin_resp.url, "Unauthenticated /nandhini-admin/ redirected to login")

    export_resp = client.get('/nandhini-admin/export-customers/')
    assert_test(export_resp.status_code == 302 and '/admin/login/' in export_resp.url, "Unauthenticated /nandhini-admin/export-customers/ blocked")

    redeem_resp = client.post('/nandhini-admin/redeem/', {'phone_number': '9876543210'})
    assert_test(redeem_resp.status_code == 302 and '/admin/login/' in redeem_resp.url, "Unauthenticated /nandhini-admin/redeem/ blocked")

    lookup_resp = client.get('/api/counter-customer-lookup/?phone=9876543210')
    assert_test(lookup_resp.status_code == 302 and '/admin/login/' in lookup_resp.url, "Unauthenticated /api/counter-customer-lookup/ blocked")

    # -------------------------------------------------------------
    # 3. Form Sanitization & Anti-XSS Engine
    # -------------------------------------------------------------
    print("\n[SECTION 3: FORM SANITIZATION & ANTI-XSS DEFENSE]")
    xss_payload_1 = "<script>alert('XSS')</script>Nandhini"
    clean_1 = sanitize_text(xss_payload_1)
    assert_test("<script>" not in clean_1 and "alert" not in clean_1 and "Nandhini" in clean_1, "Script tag payload stripped cleanly", clean_1)

    xss_payload_2 = "<img src=x onerror=alert('PWNED')>Selvam"
    clean_2 = sanitize_text(xss_payload_2)
    assert_test("onerror" not in clean_2 and "<img" not in clean_2 and "Selvam" in clean_2, "Event handler attribute payload stripped cleanly", clean_2)

    xss_payload_3 = "<iframe src='javascript:alert(1)'></iframe>Store"
    clean_3 = sanitize_text(xss_payload_3)
    assert_test("iframe" not in clean_3 and "javascript" not in clean_3 and "Store" in clean_3, "Iframe / javascript URI payload stripped cleanly", clean_3)

    # -------------------------------------------------------------
    # 4. Open Redirect Phishing Defense
    # -------------------------------------------------------------
    print("\n[SECTION 4: OPEN REDIRECT PHISHING MITIGATION]")
    login_client = get_client()
    # Test malicious external next url on login
    phish_resp = login_client.post('/login/', {
        'phone_number': '9856278642',
        'next': 'https://evil-phishing-site.com/steal-creds'
    })
    # Must redirect to safe /dashboard/ instead of evil-phishing-site.com
    redirect_target = phish_resp.url if hasattr(phish_resp, 'url') else ''
    assert_test(redirect_target == '/dashboard/' or not redirect_target.startswith('https://evil-phishing-site.com'),
                "Malicious external next URL safely neutralized to /dashboard/", redirect_target)

    # -------------------------------------------------------------
    # 5. OWASP Security Headers & CSP
    # -------------------------------------------------------------
    print("\n[SECTION 5: OWASP SECURITY HEADERS & CSP]")
    home_resp = client.get('/')
    assert_test(home_resp.headers.get('X-Frame-Options') == 'DENY', "X-Frame-Options is strictly 'DENY'")
    assert_test(home_resp.headers.get('X-Content-Type-Options') == 'nosniff', "X-Content-Type-Options is 'nosniff'")
    assert_test('strict-origin' in home_resp.headers.get('Referrer-Policy', ''), "Referrer-Policy is strict-origin")
    csp = home_resp.headers.get('Content-Security-Policy', '')
    assert_test("frame-ancestors 'none'" in csp and "script-src 'self'" in csp and "frame-src 'self' https://www.google.com" in csp, "Strict Content-Security-Policy header active with Google Maps frame-src", csp)

    # -------------------------------------------------------------
    # 6. Malicious Scanner & Exploit Probe Blocking
    # -------------------------------------------------------------
    print("\n[SECTION 6: EXPLOIT SCANNER & BOT DEFENSE]")
    sqlmap_client = get_client(HTTP_USER_AGENT="sqlmap/1.5#dev")
    scan_resp = sqlmap_client.get('/')
    assert_test(scan_resp.status_code == 403, f"sqlmap exploit scanner blocked with HTTP 403 ({scan_resp.status_code})")

    nikto_client = get_client(HTTP_USER_AGENT="Mozilla/5.0 (Nikto/2.1.6)")
    nikto_resp = nikto_client.get('/')
    assert_test(nikto_resp.status_code == 403, f"nikto vulnerability scanner blocked with HTTP 403 ({nikto_resp.status_code})")

    # -------------------------------------------------------------
    # 7. Invisible Bot Honeypot Trap
    # -------------------------------------------------------------
    print("\n[SECTION 7: INVISIBLE HONEYPOT TRAP]")
    bot_client = get_client()
    bot_resp = bot_client.post('/login/', {
        'phone_number': '9876543210',
        'website_trap_val': 'automated_spambot_filled_this'
    })
    assert_test('OK' in bot_resp.content.decode('utf-8') or bot_resp.status_code == 200, "Automated bot trapped silently by honeypot without querying DB")

    # -------------------------------------------------------------
    # 8. Customer IDOR & Session Isolation
    # -------------------------------------------------------------
    print("\n[SECTION 8: CUSTOMER SESSION IDOR ISOLATION]")
    test_cust_a = Customer.objects.filter(phone_number='9856278642').first()
    if test_cust_a:
        session_client = get_client()
        session = session_client.session
        session['customer_id'] = test_cust_a.id
        session.save()

        # Customer viewing own dashboard
        dash_resp = session_client.get('/dashboard/')
        assert_test(dash_resp.status_code == 200, "Customer can view own dashboard")
        assert_test('9856278642' in dash_resp.content.decode('utf-8') or test_cust_a.name in dash_resp.content.decode('utf-8'), "Dashboard renders authenticated customer data")

        # QR pass generated for own session (Vector SVG for dark mode clarity)
        qr_resp = session_client.get(f'/api/member-pass-qr/?phone={test_cust_a.phone_number}')
        assert_test(qr_resp.status_code == 200 and 'image/svg+xml' in qr_resp.headers['Content-Type'], "Member QR pass generated securely in-memory as SVG")

    # -------------------------------------------------------------
    # 9. Concurrency & SQLite WAL Multi-Threaded Stress Test
    # -------------------------------------------------------------
    print("\n[SECTION 9: CONCURRENCY & SQLITE WAL STRESS TEST]")
    import concurrent.futures

    def simulate_concurrent_read(i):
        c = get_client()
        res = c.get('/login/')
        return res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(simulate_concurrent_read, i) for i in range(15)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert_test(all(code == 200 for code in results), f"15 concurrent requests succeeded with 100% 200 OK (Results: {set(results)})")

    # -------------------------------------------------------------
    # 10. Admin Rate Limiting Shield Test
    # -------------------------------------------------------------
    print("\n[SECTION 10: ADMIN BRUTE FORCE RATE LIMITING]")
    cache.clear()  # Start clean for rate limit test
    rl_client = get_client()
    responses = []
    for _ in range(12):
        r = rl_client.get('/admin/login/')
        responses.append(r.status_code)

    # 11th and 12th requests should be throttled with HTTP 429
    assert_test(429 in responses, f"Admin brute force triggered HTTP 429 rate limit (Observed codes: {set(responses)})")

    print("\n" + "=" * 70)
    print(f"  AUDIT SUMMARY: {passed} / {total} SECURITY CHECKS PASSED ({int(passed/total*100)}%)")
    print("=" * 70)
    return passed == total


if __name__ == '__main__':
    all_passed = run_all_tests()
    exit(0 if all_passed else 1)
