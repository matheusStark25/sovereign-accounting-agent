from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseAgent(ABC):
    """Abstract base class for runtime agents (plugin-friendly).

    Implementations must provide a `process` entrypoint and a small
    `get_metadata` method used for discovery in the backend.
    """

    @abstractmethod
    def process(self, input_data: dict, context: Optional[dict] = None) -> dict:
        """Process an incoming request payload and return a dict response."""

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """Return a small metadata dict (name, version, description).

        Used by the discovery endpoint `/v1/agents`.
        """
