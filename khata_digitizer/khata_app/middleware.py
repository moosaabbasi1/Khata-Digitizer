"""
Security and Defensive Traffic Middleware for Khata Digitizer.
Provides Content Security Policy (CSP), permissions policies, defensive response
headers, and IP-based rate limiting on sensitive authentication/upload endpoints.
"""

import time
from django.core.cache import cache
from django.http import HttpResponse


class SecurityHeadersMiddleware:
    """
    Enforces strict security headers (CSP, Permissions-Policy, COOP) across all responses.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Content Security Policy (CSP)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
            "font-src 'self' https://fonts.gstatic.com data:",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # Permissions Policy & Cross-Origin isolation
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(), payment=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


class RateLimitMiddleware:
    """
    Lightweight rate-limiter on authentication and upload routes to defend against
    brute-force password guessing, credential stuffing, and DoS image flooding.
    """
    def __init__(self, get_response):
        self.get_response = get_response

        # Route rate limits: (max_requests, window_seconds)
        self.throttled_paths = {
            "/login/": (15, 60),        # Max 15 attempts per minute per IP
            "/register/": (10, 60),     # Max 10 registrations per minute per IP
            "/chits/upload/": (25, 60), # Max 25 chit uploads per minute per IP
        }

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR", "127.0.0.1")
        return ip

    def __call__(self, request):
        if request.method == "POST":
            path = request.path
            for route, (max_reqs, window_sec) in self.throttled_paths.items():
                if path.startswith(route):
                    ip = self._get_client_ip(request)
                    cache_key = f"rl_{route}_{ip}"
                    current_count = cache.get(cache_key, 0)

                    if current_count >= max_reqs:
                        return HttpResponse(
                            "Too many requests from your IP. Please wait a minute before trying again.",
                            status=429,
                            content_type="text/plain",
                        )

                    cache.set(cache_key, current_count + 1, window_sec)
                    break

        return self.get_response(request)
