"""
Security headers middleware: CORS, CSP, HSTS, etc.
"""

import os
from typing import List, Optional

from flask import make_response, request


class SecurityHeaders:
    """Adiciona headers de segurança a responses."""

    DEFAULT_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.socket.io https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "style-src-elem 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "connect-src 'self' https://api.groq.com ws: wss:; "
        "frame-ancestors 'self';"
    )

    @staticmethod
    def apply_cors_headers(response, allowed_origins: Optional[List[str]] = None):
        """Aplica headers CORS."""
        if allowed_origins is None:
            allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "*")
            allowed_origins = allowed_origins_str.split(",")

        origin = request.headers.get("Origin", "")

        if "*" in allowed_origins or origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-API-Key, X-Empresa-ID, X-Trace-Id"
            )
            response.headers["Access-Control-Max-Age"] = "3600"

        return response

    @staticmethod
    def apply_security_headers(response):
        """Aplica headers de segurança padrão."""
        # Content Security Policy
        response.headers["Content-Security-Policy"] = SecurityHeaders.DEFAULT_CSP

        # Strict Transport Security (HTTPS only)
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Previne clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # Previne MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosnif"

        # XSS Protection (header legado mas ainda útil)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy (Feature Policy)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response

    @staticmethod
    def setup_app(app, allowed_origins: Optional[List[str]] = None):
        """Configura app Flask com security headers."""

        @app.after_request
        def add_security_headers(response):
            response = SecurityHeaders.apply_security_headers(response)
            response = SecurityHeaders.apply_cors_headers(response, allowed_origins)
            return response

        @app.before_request
        def handle_preflight():
            """Handle OPTIONS requests for CORS."""
            if request.method == "OPTIONS":
                response = make_response("", 204)
                response = SecurityHeaders.apply_cors_headers(response, allowed_origins)
                return response

        return app
