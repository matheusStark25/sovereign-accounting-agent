from __future__ import annotations
from typing import Protocol, Any, Dict
from models.rescisao import RescisaoInput


class CalculoToolProtocol(Protocol):
    def calculate(self, resc: RescisaoInput) -> Dict[str, Any]:
        """Calculate results for a `RescisaoInput`.

        Implementations should return a serializable dict with computed fields.
        """
        pass


class PDFToolProtocol(Protocol):
    def generate_pdf(self, payload: Dict[str, Any]) -> bytes:
        """Generate a PDF from the calculated payload and return bytes."""
        pass


class AuditServiceProtocol(Protocol):
    def info(self, msg: str) -> None:
        """Log an informational message."""
        pass

    def error(self, msg: str) -> None:
        """Log an error message."""
        pass

    def critical(self, msg: str) -> None:
        """Log a critical error message."""
        pass
