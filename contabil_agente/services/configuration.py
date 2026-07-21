"""Hierarchical configuration loader: Env Vars > YAML file > Defaults."""

import os

try:
    import yaml  # type: ignore
except Exception:
    # Fallback shim if PyYAML is not installed. This allows the module to work
    # in environments where only the standard library is available by
    # attempting to parse simple JSON as a subset of YAML.
    import json as _json

    class _YamlShim:
        @staticmethod
        def safe_load(stream):
            try:
                # support file-like objects and strings
                if hasattr(stream, "read"):
                    return _json.load(stream)
                return _json.loads(stream)
            except Exception:
                return None

    yaml = _YamlShim()
from typing import Any, Dict, Optional


class Configuration:
    def __init__(
        self, yaml_path: Optional[str] = None, defaults: Optional[Dict[str, Any]] = None
    ):
        self.yaml_path = yaml_path or os.getenv("AGENT_CONFIG_YAML")
        self.defaults = defaults or {}
        self._yaml = None
        if self.yaml_path and os.path.exists(self.yaml_path):
            try:
                with open(self.yaml_path, "r", encoding="utf-8") as fh:
                    self._yaml = yaml.safe_load(fh) or {}
            except Exception:
                self._yaml = {}
        else:
            self._yaml = {}

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        # Env takes precedence
        if key in os.environ:
            return os.environ[key]
        # YAML next
        if self._yaml and key in self._yaml:
            return self._yaml[key]
        # defaults
        if key in self.defaults:
            return self.defaults[key]
        return default


_global = None


def get_config(
    yaml_path: Optional[str] = None, defaults: Optional[Dict[str, Any]] = None
) -> Configuration:
    global _global
    if _global is None:
        _global = Configuration(yaml_path=yaml_path, defaults=defaults)
    return _global


__all__ = ["get_config", "Configuration"]
