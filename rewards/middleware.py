import re
import time
import logging
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.db.utils import OperationalError

logger = logging.getLogger('rewards.security')

# Signatures of known malicious automated scanners and vulnerability probe tools
MALICIOUS_USER_AGENTS = (
    'sqlmap', 'nikto', 'acunetix', 'dirbuster', 'nmap', 'masscan',
    'wpscan', 'havij', 'zgrab', 'censys', 'shodan', 'fuzz',
    'morfeus', 'zmeu', 'gobuster', 'wfuzz', 'vega'
)

# Sensitive paths requiring tighter throttling
SENSITIVE_PATHS = ('/login/', '/api/check-phone/', '/claim/', '/scan-token/')
ADMIN_PATHS = ('/admin/login/', '/nandhini-admin/')


def get_client_ip(request):
    """Accurately extracts client IP behind local proxies or direct connections"""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


class SecurityAndBotShieldMiddleware:
    """
    Production-Grade Defense & Concurrency Shield:
    1. Blocks automated scanners, exploit probes, and malicious user-agents.
    2. Catches automated bot submissions using invisible honeypots.
    3. Sliding-window IP rate limiting prevents DDoS and brute-force token enumeration.
    4. Automatically recovers from transient SQLite lock collisions with backoff retry.
    5. Injects modern OWASP security headers (Clickjacking, MIME-sniffing, XSS protection).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_ip = get_client_ip(request)
        path = request.path
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()

        # -----------------------------------------------------------
        # 1. SHIELD: Malicious Bot & Vulnerability Scanner Blocking
        # -----------------------------------------------------------
        if any(sig in user_agent for sig in MALICIOUS_USER_AGENTS):
            logger.warning(f"Blocked malicious scanner signature from IP {client_ip} (UA: {user_agent})")
            return HttpResponse("Access Denied", status=403, content_type="text/plain")

        # -----------------------------------------------------------
        # 2. SHIELD: Invisible Honeypot Trap
        # Bots automatically fill every input field on forms.
        # Legitimate humans cannot see or tab into 'website_trap_val'.
        # -----------------------------------------------------------
        honeypot_val = request.POST.get('website_trap_val') or request.GET.get('website_trap_val')
        if honeypot_val:
            logger.info(f"Honeypot triggered by automated bot from IP {client_ip}")
            # Silently drop without consuming database resources
            return render(request, 'rewards/error.html', {
                'title': 'Request Processed',
                'message': 'Your request has been verified.',
                'code': 'OK'
            })

        # -----------------------------------------------------------
        # 3. SHIELD: Sliding-Window IP Rate Limiting (DDoS & Brute-Force)
        # -----------------------------------------------------------
        is_staff_user = bool(
            getattr(request, 'user', None)
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )

        # 3A. IP Ban Check (Always bypass for authenticated staff & loopback)
        ban_key = f"banned_ip_{client_ip}"
        if not is_staff_user and client_ip not in ('127.0.0.1', '::1') and cache.get(ban_key):
            return render(request, 'rewards/error.html', {
                'title': 'Traffic Paused',
                'message': 'Excessive requests detected from your device. Access is temporarily paused for security. Please try again shortly.',
                'code': 'ERR_RATE_LIMIT'
            }, status=429)

        # 3B. Admin Login Brute-Force Shield (Only protects POST submissions, max 25 per 5 mins)
        # Normal GET browsing / viewing admin pages is completely permitted
        if not is_staff_user and request.method == 'POST' and any(path.startswith(ap) for ap in ADMIN_PATHS):
            admin_rate_key = f"admin_rate_{client_ip}"
            admin_hits = cache.get(admin_rate_key, 0)
            if admin_hits > 25:
                cache.set(ban_key, True, timeout=180)  # Brief 3-minute cooldown
                logger.warning(f"Admin brute force threshold exceeded for IP {client_ip}")
                err_resp = render(request, 'rewards/error.html', {
                    'title': 'Admin Route Locked',
                    'message': 'Multiple login attempts detected. Access is briefly paused for 3 minutes for store security.',
                    'code': 'ERR_ADMIN_RATE_LIMIT'
                }, status=429)
                err_resp['Retry-After'] = '180'
                return err_resp
            cache.set(admin_rate_key, admin_hits + 1, timeout=300)

        # 3C. Sensitive Auth & Claim Paths (Max 50 requests per minute)
        if not is_staff_user and any(path.startswith(sp) for sp in SENSITIVE_PATHS):
            auth_rate_key = f"auth_rate_{client_ip}"
            auth_hits = cache.get(auth_rate_key, 0)
            if auth_hits > 50:
                cache.set(ban_key, True, timeout=180)  # 3-minute cooldown
                logger.warning(f"Rate limit exceeded on auth/claim for IP {client_ip}")
                return render(request, 'rewards/error.html', {
                    'title': 'Too Many Attempts',
                    'message': 'Too many scan or login attempts from this network. Please wait 3 minutes before trying again.',
                    'code': 'ERR_AUTH_RATE_LIMIT'
                }, status=429)
            cache.set(auth_rate_key, auth_hits + 1, timeout=60)

        # 3D. Global Request Limiting (Exclude background polling endpoints & staff)
        is_background_poll = path.startswith('/api/latest-broadcast/') or path.startswith('/sw.js') or path.startswith('/static/')
        if not is_staff_user and not is_background_poll:
            global_rate_key = f"global_rate_{client_ip}"
            global_hits = cache.get(global_rate_key, 0)
            # Higher limit for localhost/loopback testing
            max_global = 1000 if client_ip in ('127.0.0.1', '::1') else 400
            if global_hits > max_global:
                if client_ip not in ('127.0.0.1', '::1'):
                    cache.set(ban_key, True, timeout=120)  # 2-minute cooldown
                return render(request, 'rewards/error.html', {
                    'title': 'Network Congestion',
                    'message': 'Server is receiving too many rapid requests. Please wait 2 minutes.',
                    'code': 'ERR_BURST_LIMIT'
                }, status=429)
            cache.set(global_rate_key, global_hits + 1, timeout=60)

        # -----------------------------------------------------------
        # 4. EXECUTION: Safe Execution with Transient Lock Auto-Retry
        # -----------------------------------------------------------
        response = None
        for attempt in range(2):
            try:
                response = self.get_response(request)
                break
            except OperationalError as db_err:
                if 'database is locked' in str(db_err).lower() and attempt == 0:
                    time.sleep(0.08)  # 80ms backoff and retry once
                    continue
                logger.error(f"Database concurrency error handled gracefully: {db_err}")
                return render(request, 'rewards/error.html', {
                    'title': 'High Store Foot-Traffic',
                    'message': 'Many customers are collecting points right now! Please wait 2 seconds and tap claim again.',
                    'code': 'ERR_BUSY_RETRY'
                }, status=503)

        if response is None:
            return HttpResponse("Server Busy", status=503)

        # -----------------------------------------------------------
        # 5. HARDENING: OWASP Security Headers Injection
        # -----------------------------------------------------------
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'
        response['Content-Security-Policy'] = (
            "default-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https://cdn-icons-png.flaticon.com; "
            "connect-src 'self' https://cdn.tailwindcss.com; "
            "frame-src 'self' https://www.google.com https://maps.google.com; "
            "frame-ancestors 'none';"
        )

        return response
