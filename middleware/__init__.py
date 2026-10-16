"""
Compatibility shim package so routes importing top-level `middleware` still
work when the real modules live under `contabil_agente.middleware`.
This keeps the dev server importable without changing many route files.
"""

import importlib
import types

try:
    real = importlib.import_module("contabil_agente.middleware")
    # Export attributes from the real package
    for _attr in dir(real):
        if not _attr.startswith("__"):
            globals()[_attr] = getattr(real, _attr)
except Exception:
    # Provide an empty module that route imports can reference.
    pass
