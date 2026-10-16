from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class AnaliseResultado:
    code: Optional[str]
    message: str
    severity: str  # 'fatal' | 'warning' | 'info'
    probable_cause: Optional[str]
    suggested_action: Optional[str]


class AnalistaDeErros:
    """Analisa arquivos de log/erro e identifica padrões conhecidos.

    O analista expõe `analisar_text` e `analisar_arquivo`.
    """

    # patterns: tuple(regex, code, severity, probable_cause, suggested_action)
    PATTERNS = [
        (
            r"Erro\s*0*21|Erro\s*0021 - Inscrição Inválida",
            "0021",
            "fatal",
            "Inscrição inválida ou ausente",
            "Verifique a inscrição do contribuinte no sistema legado.",
        ),
        (
            r"timeout_no_ack|Timeout.*ack",
            "T001",
            "warning",
            "Timeout na transmissão",
            "Tentar retransmissão; verificar conectividade.",
        ),
        (
            r"Campo faltando|Campo ausente",
            "L001",
            "warning",
            "Layout incompleto",
            "Corrigir layout do arquivo e reenviar.",
        ),
        (
            r"Certificate.*expired|certificado.*expirad",
            "S001",
            "fatal",
            "Certificado digital inválido/expirado",
            "Renovar/instalar certificado digital.",
        ),
        (
            r"Erro\s*0*05|Erro\s*0005",
            "0005",
            "fatal",
            "CPF/CNPJ inválido",
            "Revisar cadastros e corrigir CPFs/CNPJs.",
        ),
    ]

    def __init__(self):
        # compile regexes
        self._compiled = [
            (re.compile(p, re.IGNORECASE), code, sev, cause, action)
            for (p, code, sev, cause, action) in self.PATTERNS
        ]

    def analisar_text(self, text: str) -> Dict[str, object]:
        findings: List[AnaliseResultado] = []
        for cre, code, sev, cause, action in self._compiled:
            m = cre.search(text)
            if m:
                findings.append(
                    AnaliseResultado(
                        code=code,
                        message=m.group(0),
                        severity=sev,
                        probable_cause=cause,
                        suggested_action=action,
                    )
                )

        if not findings:
            return {"severity": "ok", "findings": []}

        # determine overall severity: fatal > warning > info
        overall = "info"
        for f in findings:
            if f.severity == "fatal":
                overall = "fatal"
                break
            if f.severity == "warning":
                overall = "warning"

        return {"severity": overall, "findings": [f.__dict__ for f in findings]}

    def analisar_arquivo(self, path: str) -> Dict[str, object]:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            return self.analisar_text(txt)
        except FileNotFoundError:
            return {"severity": "ok", "findings": []}
        except Exception:
            return {
                "severity": "warning",
                "findings": [
                    {
                        "code": None,
                        "message": "Erro ao ler arquivo de log",
                        "severity": "warning",
                        "probable_cause": None,
                        "suggested_action": "Verificar permissões do arquivo.",
                    }
                ],
            }
