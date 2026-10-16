"""Triagem cognitiva baseada em termos contábeis com hot-reload de regras YAML.

Publica eventos via EventBus. Se OCR/qualidade fraca -> INPUT_REJECTED.
"""

from __future__ import annotations

import os
import time
import threading
import re
import yaml
import logging
from typing import Dict, Any, Optional

from contabil_agente.services.parser_service import ParserService
from contabil_agente.services.event_bus import get_event_bus
from contabil_agente.services.database_service import DatabaseService

logger = logging.getLogger("triagem_cognitiva")


class TriagemCognitiva:
    def __init__(self, rules_path: Optional[str] = None):
        self.rules_path = rules_path or os.path.join(
            os.path.dirname(__file__), "..", "legacy_mappings.yaml"
        )
        self._last_mtime = 0
        self._rules = {}
        self._lock = threading.Lock()
        self.db = DatabaseService()
        self.bus = get_event_bus()
        self.parser = ParserService()
        self._load_rules()
        # watcher thread
        t = threading.Thread(
            target=self._watcher, daemon=True, name="TriagemRulesWatcher"
        )
        t.start()

    def _load_rules(self):
        try:
            if not os.path.exists(self.rules_path):
                return
            m = os.path.getmtime(self.rules_path)
            if m == self._last_mtime:
                return
            with open(self.rules_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            # validate basic shape
            if not isinstance(data, dict):
                raise ValueError("rules must be a mapping")
            with self._lock:
                self._rules = data
                self._last_mtime = m
            # snapshot to audit logs
            try:
                self.db.log_audit(
                    "info",
                    "triagem_cognitiva",
                    "rules_reload",
                    {"path": self.rules_path, "timestamp": int(time.time())},
                )
            except Exception:
                pass
            logger.info("Triagem rules reloaded %s", self.rules_path)
        except Exception as e:
            logger.exception("failed to load rules: %s", e)

    def _watcher(self):
        while True:
            try:
                self._load_rules()
            except Exception:
                pass
            time.sleep(2)

    def classify(self, filepath: str) -> Dict[str, Any]:
        # parse text
        parsed = self.parser.parse_pdf(filepath)
        text = parsed.ocr_text or ""
        # compute OCR quality: heuristic based on length
        quality = min(1.0, len(text) / 2000.0)
        if quality < 0.25:
            # publish rejected
            cid = None
            try:
                cid = str(int(time.time() * 1000))
                self.db.save_classification_decision(
                    cid,
                    "triagem_cognitiva",
                    float(quality),
                    "INPUT_REJECTED",
                    {"path": filepath},
                )
            except Exception:
                pass
            try:
                self.bus.publish(
                    "document.input_rejected",
                    {"path": filepath, "quality": quality},
                    correlation_id=cid,
                )
            except Exception:
                pass
            return {"decision": "INPUT_REJECTED", "quality": quality}

        # run regex patterns from rules to detect DP/FISCAL
        decision = "DP"
        with self._lock:
            patterns = (
                self._rules.get("patterns", {}) if isinstance(self._rules, dict) else {}
            )
        # fallback simple regexes
        fiscal_patterns = [
            r"\bNFE\b",
            r"\bNF-e\b",
            r"\bTRCT\b",
            r"inscri[cç][aã]o municipal",
            r"id de recolhimento",
        ]
        combined = []
        if isinstance(patterns, dict):
            for k, v in patterns.items():
                try:
                    if isinstance(v, list):
                        combined += v
                except Exception:
                    continue
        combined += fiscal_patterns

        for pat in combined:
            try:
                if re.search(pat, text, flags=re.IGNORECASE):
                    decision = "FISCAL"
                    break
            except Exception:
                continue

        cid = None
        try:
            cid = str(int(time.time() * 1000))
            self.db.save_classification_decision(
                cid, "triagem_cognitiva", float(quality), decision, {"path": filepath}
            )
        except Exception:
            pass
        try:
            self.bus.publish(
                "document.triage_result",
                {"decision": decision, "path": filepath, "quality": quality},
                correlation_id=cid,
            )
        except Exception:
            pass
        return {"decision": decision, "quality": quality}


__all__ = ["TriagemCognitiva"]
