import logging
from django.http import HttpResponse
from django.db.utils import OperationalError

logger = logging.getLogger('rewards.security')


class SecurityAndBotShieldMiddleware:
    """
    Standard Production Web Security Middleware:
    1. Injects modern OWASP security headers (Clickjacking, MIME-sniffing, XSS protection).
    2. Handles transient database concurrency with quick retry.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        for attempt in range(2):
            try:
                response = self.get_response(request)
                break
            except OperationalError as db_err:
                if 'database is locked' in str(db_err).lower() and attempt == 0:
                    import time
                    time.sleep(0.08)
                    continue
                logger.error(f"Database concurrency error: {db_err}")
                raise

        if response is None:
            return HttpResponse("Server Error", status=500)

        # OWASP Security Headers
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
