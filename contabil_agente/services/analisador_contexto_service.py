import logging
import re
import unicodedata
import threading
import json
import os
import time
from typing import Any, Dict, Optional, Callable, List
from functools import lru_cache

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "correcoes": {
        "recisao": "rescisão",
        "ferias": "férias",
        "jao": "joão",
        "funcinario": "funcionário",
        "calculo": "cálculo",
    },
    "palavras_simples": ["como", "fazer", "preciso", "onde", "quando", "ajuda", "me"],
    "terms_idoso": [
        "aposentadoria",
        "aposentado",
        "pensão",
        "previdência",
        "benefício",
    ],
}


def _mask_sensitive(text: str) -> str:
    """Mask CPFs, CNPJs and monetary values for logs."""
    if not text:
        return text

    # CPF patterns
    text = re.sub(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b", "<CPF_REDACTED>", text)
    text = re.sub(r"\b(\d{11})\b", "<CPF_REDACTED>", text)

    # CNPJ patterns
    text = re.sub(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b", "<CNPJ_REDACTED>", text)
    text = re.sub(r"\b(\d{14})\b", "<CNPJ_REDACTED>", text)

    # Money amounts like R$ 1.234,56 or 1234.56
    text = re.sub(r"R\$\s*[\d\.,]+", "<MONEY>", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", "<MONEY>", text)

    return text


class AnalisadorContextoService:
    """Motor de análise de contexto seguro, testável e sem singleton global.

    Crie instâncias independentes para testes concorrentes.
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        config_path: Optional[str] = None,
        plugins: Optional[List[Callable]] = None,
        cache_size: int = 2048,
    ):
        # Load config hierarchy: explicit config > ENV path > config_path file > defaults
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg = {**cfg, **config}

        env_path = os.getenv("ANALISADOR_CONFIG_PATH")
        path_to_try = config_path or env_path
        if path_to_try:
            try:
                with open(path_to_try, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                cfg = {**cfg, **loaded}
            except Exception:
                logger.warning(
                    "Failed to load external config %s; using defaults",
                    _mask_sensitive(str(path_to_try)),
                )

        self.config = cfg
        self.plugins = plugins or []

        # Internal metrics
        self._metrics_lock = threading.Lock()
        self._total_calls = 0
        self._cache_hits = 0
        self._total_time = 0.0

        # Caching wrapper around analyze core
        self._analyze_core = self._analyze_core_impl
        self._analyze = lru_cache(maxsize=cache_size)(self._analyze_core_cached)

        # Precompile regexes for performance
        self._re_prompt_injection = re.compile(
            r"ignore (previous|all) instructions|disregard previous|ignore previous",
            re.IGNORECASE,
        )
        self._re_xss = re.compile(
            r"<script\b|<iframe\b|onerror=|onload=", re.IGNORECASE
        )

    # --- Sanitization and normalization ---
    def sanitize_input(self, text: str) -> str:
        """Perform multiple levels of sanitization to protect against prompt injection and XSS."""
        if not text or not isinstance(text, str):
            return ""

        # Remove null bytes and control characters except common whitespace
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)

        # Strip common prompt-injection phrases
        if self._re_prompt_injection.search(cleaned):
            cleaned = self._re_prompt_injection.sub("", cleaned)
            logger.warning("prompt_injection_attempt_masked")

        # Remove simple XSS vectors
        if self._re_xss.search(cleaned):
            cleaned = self._re_xss.sub("", cleaned)
            logger.warning("xss_vector_removed")

        # Normalize unicode, with fallback to ASCII transliteration
        try:
            normalized = unicodedata.normalize("NFKC", cleaned).strip()
        except Exception:
            try:
                normalized = cleaned.encode("ascii", "ignore").decode("ascii")
            except Exception:
                normalized = re.sub(r"[^\x00-\x7F]+", "", cleaned)

        return normalized

    def _normalize_with_corrections(self, text: str) -> str:
        """Apply configured corrections; resilient to errors."""
        if not text:
            return ""
        normalized = text
        try:
            corrections = self.config.get("correcoes", {})
            tokens = normalized.split()
            out = []
            for t in tokens:
                key = t.lower()
                if key in corrections:
                    corr = corrections[key]
                    if t[0].isupper():
                        corr = corr[0].upper() + corr[1:]
                    out.append(corr)
                else:
                    out.append(t)
            return " ".join(out)
        except Exception:
            logger.debug("corrections_failed")
            return text

    # --- Analyze entrypoint (cached) ---
    def _analyze_core_cached(self, text: str, historico_json: Optional[str] = None):
        # Convert historico (unhashable) to string for cache key
        historico = None
        if historico_json:
            try:
                historico = json.loads(historico_json)
            except Exception:
                historico = None
        return self._analyze_core_impl(text, historico)

    def _analyze_core_impl(
        self, text: str, historico: Optional[list] = None
    ) -> Dict[str, Any]:
        start = time.time()
        with self._metrics_lock:
            self._total_calls += 1

        safe_text = self.sanitize_input(text)
        # Attempt normalization with unicode then fallback
        try:
            normalized = self._normalize_with_corrections(safe_text)
        except Exception:
            try:
                normalized = safe_text.encode("ascii", "ignore").decode("ascii")
            except Exception:
                normalized = re.sub(r"[^\x00-\x7F]+", "", safe_text)

        # Detect profile (kept similar logic but using config-driven terms)
        perfil_info = self._detect_profile(normalized, historico=historico)
        contexto = self._extract_context(normalized)

        # Plugins can augment result; failures are isolated
        plugin_results = {}
        for plugin in self.plugins:
            try:
                res = plugin(normalized, contexto)
                if res:
                    plugin_results[getattr(plugin, "__name__", str(plugin))] = res
            except Exception:
                logger.debug(
                    "plugin_failed: %s", getattr(plugin, "__name__", str(plugin))
                )

        elapsed = time.time() - start
        with self._metrics_lock:
            self._total_time += elapsed

        return {
            "original": text,
            "normalizada": normalized,
            "perfil": perfil_info.get("perfil"),
            "scores": perfil_info.get("scores"),
            "contexto": contexto,
            "plugins": plugin_results,
            "time": elapsed,
        }

    def analyze(
        self, mensagem: str, historico: Optional[list] = None
    ) -> Dict[str, Any]:
        """Public API: analyzes message. Uses caching for identical inputs.

        Note: historico is serialized for caching; if it's large, consider passing None.
        """
        historico_json = None
        if historico is not None:
            try:
                historico_json = json.dumps(historico, ensure_ascii=False)
            except Exception:
                historico_json = None

        key_text = mensagem or ""
        # Attempt to use cache
        try:
            result = self._analyze(key_text, historico_json)
            with self._metrics_lock:
                self._cache_hits += 1
            return result
        except Exception:
            # If cache wrapper fails, call core directly
            return self._analyze_core_impl(mensagem, historico)

    # ---- Detection and extraction methods (adapted from original) ----
    def _detect_profile(
        self, mensagem: str, historico: Optional[list] = None
    ) -> Dict[str, Any]:
        # simplified but safe scoring using config
        termos_idoso = [t.lower() for t in self.config.get("terms_idoso", [])]
        termos_rural = (
            [t.lower() for t in self.config.get("terms_rural", [])]
            if self.config.get("terms_rural")
            else []
        )
        termos_prof = (
            [t.lower() for t in self.config.get("terms_profissionais", [])]
            if self.config.get("terms_profissionais")
            else []
        )

        score_idoso = sum(3 for termo in termos_idoso if termo in mensagem.lower())
        score_rural = sum(4 for termo in termos_rural if termo in mensagem.lower())
        score_prof = sum(4 for termo in termos_prof if termo in mensagem.lower())

        scores = {
            "idoso": score_idoso,
            "rural": score_rural,
            "profissional": score_prof,
        }
        perfil = (
            max(scores, key=scores.get) if max(scores.values()) > 0 else "profissional"
        )

        # Log decision with masking
        logger.info(
            _mask_sensitive(
                json.dumps(
                    {"perfil": perfil, "scores": scores, "preview": mensagem[:200]}
                )
            )
        )

        return {"perfil": perfil, "scores": scores}

    def _extract_context(self, mensagem: str) -> Dict[str, Any]:
        contexto = {
            "tipo_empresa": None,
            "regime_tributario": None,
            "funcionarios": None,
            "faturamento": None,
            "localidade": None,
        }

        if re.search(
            r"simples\s*nacional|anexo\s+[iI]+[iI]*|simples", mensagem, re.IGNORECASE
        ):
            contexto["regime_tributario"] = "simples_nacional"
        elif re.search(r"presumido|lucro\s+presumido", mensagem, re.IGNORECASE):
            contexto["regime_tributario"] = "lucro_presumido"
        elif re.search(r"real|lucro\s+real", mensagem, re.IGNORECASE):
            contexto["regime_tributario"] = "lucro_real"

        match = re.search(
            r"(\d+)\s*(funcion[áa]rio|colaborador|empregado)", mensagem, re.IGNORECASE
        )
        if match:
            try:
                contexto["funcionarios"] = int(match.group(1))
            except Exception:
                pass

        match = re.search(
            r"faturamento\s*(de\s*)?R?\$?\s*(\d+[.,]?\d*)", mensagem, re.IGNORECASE
        )
        if match:
            try:
                contexto["faturamento"] = float(
                    match.group(2).replace(".", "").replace(",", ".")
                )
            except Exception:
                pass

        match = re.search(
            r"(sp|são paulo|rj|rio|mg|minas|pr|paraná|rs|rio grande)",
            mensagem,
            re.IGNORECASE,
        )
        if match:
            contexto["localidade"] = match.group(1).upper()

        return contexto

    # ---- Health and metrics ----
    def health(self) -> Dict[str, Any]:
        with self._metrics_lock:
            avg_time = (
                (self._total_time / self._total_calls) if self._total_calls else 0.0
            )
            hit_rate = (
                (self._cache_hits / self._total_calls) if self._total_calls else 0.0
            )

        return {
            "total_calls": self._total_calls,
            "cache_hits": self._cache_hits,
            "avg_time": avg_time,
            "cache_hit_rate": hit_rate,
        }
