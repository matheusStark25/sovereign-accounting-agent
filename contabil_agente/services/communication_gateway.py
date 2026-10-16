"""Gateway de comunicação: SMTP (TLS) e WhatsApp (Meta API) com rate-limiting e circuit-breaker.

Uso:
  gw = CommunicationGateway()
  gw.send_email(...)
  gw.send_whatsapp(...)

Persistência de erros/circuit via DatabaseService audit_logs.
"""

from __future__ import annotations

import smtplib
import threading
import time
import logging
import requests
from email.message import EmailMessage
from typing import Optional, Dict
import os

from contabil_agente.services.database_service import DatabaseService
from contabil_agente.services.secret_manager import SecretManager

logger = logging.getLogger("communication_gateway")


class CircuitBreaker:
    def __init__(self, window_seconds: int = 300, error_threshold: float = 0.15):
        self.window = window_seconds
        self.error_threshold = error_threshold
        self.lock = threading.Lock()
        self.events = []  # list of (ts, success_bool)

    def record(self, success: bool):
        now = time.time()
        with self.lock:
            self.events.append((now, bool(success)))
            # trim
            cutoff = now - self.window
            self.events = [e for e in self.events if e[0] >= cutoff]

    def is_open(self) -> bool:
        with self.lock:
            if not self.events:
                return False
            failures = sum(1 for _, s in self.events if not s)
            total = len(self.events)
            return (failures / total) >= self.error_threshold


class RateLimiter:
    """Simple token bucket per key."""

    def __init__(self, rate: float = 1.0, capacity: float = 5.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last = time.time()
        self.lock = threading.Lock()

    def allow(self, tokens: float = 1.0) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last
            self.last = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class CommunicationGateway:
    def __init__(self):
        self.db = DatabaseService()
        self.secrets = SecretManager()
        self.smtp_limiter = RateLimiter(rate=0.5, capacity=5)
        self.whatsapp_limiter = RateLimiter(rate=1.0, capacity=20)
        self.smtp_cb = CircuitBreaker()
        self.whatsapp_cb = CircuitBreaker()

    def _log_and_alert(self, level: str, msg: str, meta: Optional[Dict] = None):
        try:
            self.db.log_audit(level, "communication_gateway", msg, meta or {})
        except Exception:
            logger.exception("audit failed")

    def send_email(
        self, to: str, subject: str, body: str, attachments: Optional[list] = None
    ) -> Dict:
        if self.smtp_cb.is_open():
            self._log_and_alert("warning", "smtp_circuit_open", {"to": to})
            return {"ok": False, "reason": "circuit_open"}

        if not self.smtp_limiter.allow():
            return {"ok": False, "reason": "rate_limited"}

        smtp_host = self.secrets.get(
            "SMTP_HOST", os.getenv("SMTP_HOST", "smtp.example.com")
        )
        smtp_port = int(self.secrets.get("SMTP_PORT", os.getenv("SMTP_PORT", "587")))
        smtp_user = self.secrets.get("SMTP_USER")
        smtp_pass = self.secrets.get("SMTP_PASS")

        msg = EmailMessage()
        msg["From"] = smtp_user or "no-reply@example.com"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as s:
                s.starttls()
                if smtp_user and smtp_pass:
                    s.login(smtp_user, smtp_pass)
                s.send_message(msg)
            self.smtp_cb.record(True)
            return {"ok": True}
        except Exception as e:
            self.smtp_cb.record(False)
            self._log_and_alert("error", f"smtp_send_failed {e}", {"to": to})
            return {"ok": False, "reason": str(e)}

    def send_whatsapp(
        self, phone: str, template: str, variables: Dict[str, str]
    ) -> Dict:
        if self.whatsapp_cb.is_open():
            self._log_and_alert("warning", "whatsapp_circuit_open", {"phone": phone})
            return {"ok": False, "reason": "circuit_open"}

        if not self.whatsapp_limiter.allow():
            return {"ok": False, "reason": "rate_limited"}

        token = self.secrets.get("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_TOKEN")
        phone_id = self.secrets.get("WHATSAPP_PHONE_ID") or os.getenv(
            "WHATSAPP_PHONE_ID"
        )
        if not token or not phone_id:
            return {"ok": False, "reason": "not_configured"}

        url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": "pt_BR"},
                "components": [],
            },
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                self.whatsapp_cb.record(True)
                return {"ok": True}
            else:
                self.whatsapp_cb.record(False)
                self._log_and_alert(
                    "error",
                    f"whatsapp_send_non200 {r.status_code}",
                    {"phone": phone, "resp": r.text},
                )
                return {
                    "ok": False,
                    "reason": f"status_{r.status_code}",
                    "body": r.text,
                }
        except Exception as e:
            self.whatsapp_cb.record(False)
            self._log_and_alert("error", f"whatsapp_send_failed {e}", {"phone": phone})
            return {"ok": False, "reason": str(e)}


__all__ = ["CommunicationGateway"]
