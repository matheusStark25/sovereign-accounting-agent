import logging
import os
from typing import Dict, Optional
import smtplib
from email.message import EmailMessage
import requests

from .secret_manager import SecretManager

logger = logging.getLogger(__name__)

try:
    from contabil_agente.services.audit_service import AuditService
except Exception:
    AuditService = None


class DeliveryService:
    """Entrega multicanal (WhatsApp/Email) com modo mock para testes.

    - Mock mode controlled by env var `DELIVERY_MOCK`.
    - send methods are best-effort and always log via audit_service.
    """

    def __init__(self, mock: Optional[bool] = None):
        if mock is None:
            self.mock = os.getenv("DELIVERY_MOCK", "true").lower() in (
                "1",
                "true",
                "yes",
            )
        else:
            self.mock = bool(mock)
        self.secrets = SecretManager()

    def _audit(self, msg: str):
        try:
            if AuditService:
                a = AuditService.get_instance()
                a.log_operation(msg)
                return
        except Exception:
            pass
        logger.info("AUDIT: %s", msg)

    def health_check(self) -> Dict[str, bool]:
        """Check presence of required credentials for delivery providers.

        Returns dict with 'smtp' and 'whatsapp' availability.
        """
        out = {"smtp": False, "whatsapp": False}
        try:
            smtp_host = self.secrets.get("SMTP_HOST")
            smtp_user = self.secrets.get("SMTP_USER")
            if smtp_host and smtp_user:
                out["smtp"] = True
        except Exception:
            out["smtp"] = False

        try:
            wa_token = self.secrets.get("WHATSAPP_TOKEN")
            if wa_token:
                out["whatsapp"] = True
        except Exception:
            out["whatsapp"] = False

        return out

    def send_whatsapp(
        self, to: str, pdf_path: str, summary: Dict[str, any], priority: str = "normal"
    ) -> Dict[str, any]:
        payload = {"to": to, "pd": pdf_path, "summary": summary, "priority": priority}
        if self.mock:
            self._audit(f"MOCK_WHATSAPP_SEND {payload}")
            return {"status": "mocked", "payload": payload}
        # Placeholder: provider SDK call
        try:
            webhook = self.secrets.get("WHATSAPP_WEBHOOK_URL")
            if not webhook:
                raise RuntimeError("No WHATSAPP_WEBHOOK_URL configured")
            files = {}
            data = {"to": to, "priority": priority}
            if pdf_path and os.path.exists(pdf_path):
                files["file"] = open(pdf_path, "rb")
            r = requests.post(webhook, data=data, files=files, timeout=30)
            if files.get("file"):
                try:
                    files["file"].close()
                except Exception:
                    pass
            if r.status_code == 200:
                self._audit(f"WHATSAPP_SENT {payload}")
                return {"status": "sent", "payload": payload}
            else:
                raise RuntimeError(f"webhook_status={r.status_code}")
        except Exception as e:
            logger.exception("Failed to send whatsapp: %s", e)
            self._audit(f"WHATSAPP_FAILED {payload}")
            return {"status": "failed", "reason": str(e)}

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: Optional[list] = None,
        priority: str = "normal",
    ) -> Dict[str, any]:
        payload = {
            "to": to,
            "subject": subject,
            "body": body,
            "attachments": attachments,
            "priority": priority,
        }
        if self.mock:
            self._audit(f"MOCK_EMAIL_SEND {payload}")
            return {"status": "mocked", "payload": payload}
        try:
            host = self.secrets.get("SMTP_HOST")
            port = int(self.secrets.get("SMTP_PORT", "587"))
            user = self.secrets.get("SMTP_USER")
            password = self.secrets.get("SMTP_PASS")
            if not host or not user:
                raise RuntimeError("SMTP not configured")
            msg = EmailMessage()
            msg["From"] = user
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            # attachments
            if attachments:
                for p in attachments:
                    try:
                        with open(p, "rb") as fh:
                            data = fh.read()
                        maintype = "application"
                        subtype = "octet-stream"
                        msg.add_attachment(
                            data,
                            maintype=maintype,
                            subtype=subtype,
                            filename=os.path.basename(p),
                        )
                    except Exception:
                        continue

            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                server = smtplib.SMTP(host, port, timeout=30)
                server.starttls()
            try:
                if user and password:
                    server.login(user, password)
                res = server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

            # send_message returns {} on success (no refused)
            if res == {}:
                self._audit(f"EMAIL_SENT {payload}")
                return {"status": "sent", "payload": payload}
            else:
                raise RuntimeError(f"smtp_refused={res}")
        except Exception as e:
            logger.exception("Failed to send email: %s", e)
            self._audit(f"EMAIL_FAILED {payload}")
            return {"status": "failed", "reason": str(e)}


__all__ = ["DeliveryService"]
