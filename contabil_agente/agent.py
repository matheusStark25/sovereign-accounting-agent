"""Core AgenteContabil class extracted from agent_contabil.py

This module contains the `AgenteContabil` class and its methods. It keeps
the same behavior as the original module but is separated to improve
maintainability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional

# Import tools with the same fallback pattern used originally
try:
    from contabil_agente.tools.calculo_tool import (  # type: ignore
        DadosFuncionario,
        DadosRescisaoCalculo,
        ToolCalculo,
    )
except Exception:
    ToolCalculo = None  # type: ignore
    DadosFuncionario = None  # type: ignore
    DadosRescisaoCalculo = None  # type: ignore

try:
    from contabil_agente.tools.pdf_tool import ToolPDF  # type: ignore
except Exception:
    ToolPDF = None  # type: ignore

try:
    from contabil_agente.tools.assinatura_tool import ToolAssinatura  # type: ignore
except Exception:
    ToolAssinatura = None  # type: ignore

try:
    from contabil_agente.utils.audit import send_audit  # type: ignore
except Exception:
    send_audit = None  # type: ignore

# Import utility helpers
from contabil_agente.utils.common import (
    safe_decimal,
)

logger = logging.getLogger("contabil_agente.agent_contabil")

try:
    from backend.interfaces import BaseAgent  # type: ignore
except Exception:
    from abc import ABC as BaseAgent  # type: ignore


class AgenteContabil(BaseAgent):
    """Orquestrador principal que coordena as ferramentas.

    Responsabilidades:
    - receber dados de entrada (dict)
    - executar cálculo (via `CalculoTool`)
    - gerar PDF (via `PDFTool`)
    - assinar/gerar hash do documento (via `SigningTool` ou SHA-256)
    - gravar evento de auditoria (via `AuditoriaTool`)

    O Agente deve delegar regras de negócio e persistência às ferramentas.
    """

    def __init__(
        self,
        calculo: Optional[Any] = None,
        pdf_tool: Optional[Any] = None,
        signing: Optional[Any] = None,
        auditoria: Optional[Any] = None,
    ):
        # Inicialização segura com fallbacks
        if calculo is not None:
            self.calculo = calculo
        elif ToolCalculo is not None:
            try:
                self.calculo = ToolCalculo()
                logger.info("✓ ToolCalculo inicializado com sucesso")
            except Exception as e:
                logger.warning(f"Falha ao inicializar ToolCalculo: {e}")
                self.calculo = None
        else:
            logger.warning("ToolCalculo não disponível (importação falhou)")
            self.calculo = None

        if pdf_tool is not None:
            self.pdf_tool = pdf_tool
        elif ToolPDF is not None:
            try:
                self.pdf_tool = ToolPDF()
            except Exception as e:
                logger.warning(f"Falha ao inicializar ToolPDF: {e}")
                self.pdf_tool = None
        else:
            self.pdf_tool = None

        if signing is not None:
            self.signing = signing
        elif ToolAssinatura is not None:
            try:
                self.signing = ToolAssinatura()
            except Exception as e:
                logger.warning(f"Falha ao inicializar ToolAssinatura: {e}")
                self.signing = None
        else:
            self.signing = None

        # auditoria may be a function (send_audit) or an object with .log
        self.auditoria = auditoria or (send_audit if send_audit is not None else None)

    def _audit(self, action: str, details: Dict[str, Any]):
        try:
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
            }
            if callable(self.auditoria):
                try:
                    # prefer send_audit(action, level, context)
                    try:
                        self.auditoria(action, level="info", context=details)
                    except Exception:
                        self.auditoria(entry)
                except Exception:
                    logger.exception("Falha ao enviar evento para auditoria")
            elif hasattr(self.auditoria, "log"):
                try:
                    self.auditoria.log(entry)
                except Exception:
                    logger.exception("Falha ao enviar evento para auditoria.object.log")
            else:
                logger.info(
                    "AUDIT %s %s",
                    action,
                    json.dumps(details, default=str, ensure_ascii=False),
                )
        except Exception:
            logger.exception("Erro ao gravar auditoria")

    def _normalize_numbers_to_decimal(self, obj: Any) -> Any:
        """Recursively convert ints/floats inside dicts/lists to Decimal.

        This helps avoid mixing Decimal and float in downstream calculations.
        """
        from decimal import Decimal as _Decimal

        if obj is None:
            return None
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                try:
                    out[k] = self._normalize_numbers_to_decimal(v)
                except Exception:
                    out[k] = v
            return out
        if isinstance(obj, list):
            return [self._normalize_numbers_to_decimal(i) for i in obj]
        if isinstance(obj, tuple):
            return tuple(self._normalize_numbers_to_decimal(i) for i in obj)
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            try:
                return _Decimal(str(obj))
            except Exception:
                return obj
        return obj

    def calcular(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """Executa o cálculo usando a ferramenta de cálculo.

        Retorna dicionário com resultado do cálculo.
        """
        # Normalize numeric inputs to Decimal to avoid mixed-type arithmetic
        try:
            dados = self._normalize_numbers_to_decimal(dados or {})
        except Exception:
            # best-effort: if normalization fails, continue with original payload
            pass

        if not self.calculo:
            logger.error("CalculoTool não disponível")
            raise RuntimeError("CalculoTool não disponível")
        try:
            self._audit("calculo.start", {"input_keys": list(dados.keys())})
            # Prefer generic executor if available
            if hasattr(self.calculo, "executar"):
                resultado = self.calculo.executar(dados)
            elif hasattr(self.calculo, "calcular_rescisao_completa"):
                # map minimal fields to DadosFuncionario / DadosRescisaoCalculo
                try:
                    df = DadosFuncionario()
                    dr = DadosRescisaoCalculo()
                    if "salario_bruto" in dados:
                        df.salario_base = safe_decimal(dados.get("salario_bruto"))
                    if "meses_trabalhados" in dados:
                        dr.meses_trabalhados_ano = int(dados.get("meses_trabalhados"))
                    resultado = self.calculo.calcular_rescisao_completa(df, dr)
                except Exception:
                    resultado = {"status": "error", "message": "input mapping failed"}
            else:
                raise RuntimeError("CalculoTool não expõe API conhecida")

            self._audit(
                "calculo.end",
                {
                    "resultado_keys": (
                        list(resultado.keys()) if isinstance(resultado, dict) else []
                    )
                },
            )
            return resultado
        except Exception as e:
            logger.exception("Erro durante cálculo: %s", e)
            self._audit("calculo.error", {"error": str(e)})
            raise

    def gerar_pdf(
        self, calculo_result: Dict[str, Any], meta: Optional[Dict[str, Any]] = None
    ) -> tuple[bytes, Optional[str]]:
        """Gera PDF a partir do resultado do cálculo e retorna bytes do arquivo."""
        # Prefer tool; if missing, we'll attempt a dynamic fallback to DocumentService
        if not self.pdf_tool:
            logger.warning(
                "PDFTool não disponível no ambiente; tentativa de fallback com DocumentService"
            )
        try:
            self._audit("pdf.start", {"meta": meta or {}})
            pdf_bytes = b""
            generated_path = None
            if self.pdf_tool is not None:
                if hasattr(self.pdf_tool, "gerar_trct"):
                    out = self.pdf_tool.gerar_trct(calculo_result)
                    if (
                        isinstance(out, dict)
                        and out.get("status") == "success"
                        and out.get("filepath")
                    ):
                        generated_path = out.get("filepath")
                elif hasattr(self.pdf_tool, "gerar_holerite"):
                    out = self.pdf_tool.gerar_holerite(calculo_result)
                    if (
                        isinstance(out, dict)
                        and out.get("status") == "success"
                        and out.get("filepath")
                    ):
                        generated_path = out.get("filepath")
                else:
                    if hasattr(self.pdf_tool, "render"):
                        try:
                            pdf_bytes = self.pdf_tool.render(calculo_result, meta or {})
                        except Exception:
                            pdf_bytes = b""
            else:
                # Fallback: use internal DocumentService to generate a professional PDF
                try:
                    filename = (
                        f"documento_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.pdf"
                    )
                    # Compose a readable content from cálculo + meta
                    try:
                        content_text = json.dumps(
                            calculo_result, ensure_ascii=False, indent=2
                        )
                    except Exception:
                        content_text = str(calculo_result)

                    metadata = meta or {}
                    metadata.setdefault("protocolo", metadata.get("request_id", "demo"))

                    ok = False
                    # import document_service lazily to avoid module import-time failures
                    try:
                        import importlib

                        mod = importlib.import_module(
                            "contabil_agente.services.document_service"
                        )
                        doc_svc = getattr(mod, "document_service", None)
                    except Exception:
                        doc_svc = None

                    try:
                        if doc_svc:
                            ok = doc_svc.generate_professional_pdf(
                                filename, content_text, metadata
                            )
                    except Exception:
                        logger.exception("Fallback DocumentService falhou ao gerar PDF")

                    if ok and doc_svc and hasattr(doc_svc, "output_folder"):
                        safe = None
                        try:
                            safe = doc_svc.sanitize_filename(filename)
                        except Exception:
                            safe = filename
                        generated_path = os.path.join(doc_svc.output_folder, safe)
                        try:
                            with open(generated_path, "rb") as f:
                                pdf_bytes = f.read()
                        except Exception:
                            logger.exception(
                                "Falha ao ler PDF gerado pelo DocumentService"
                            )
                    else:
                        # As último recurso, retornar representação textual como bytes
                        pdf_bytes = (
                            content_text
                            + "\n\n"
                            + json.dumps(metadata, ensure_ascii=False)
                        ).encode("utf-8")
                except Exception:
                    logger.exception("Erro inesperado no fallback de geração de PDF")
                    # garantia de fallback mínimo
                    try:
                        content_text = json.dumps(
                            calculo_result, ensure_ascii=False, indent=2
                        )
                    except Exception:
                        content_text = str(calculo_result)
                    pdf_bytes = (
                        content_text
                        + "\n\n"
                        + json.dumps(meta or {}, ensure_ascii=False)
                    ).encode("utf-8")

            if generated_path:
                try:
                    with open(generated_path, "rb") as f:
                        pdf_bytes = f.read()
                except Exception:
                    logger.exception("Falha ao ler arquivo PDF gerado")

            self._audit("pdf.end", {"size_bytes": len(pdf_bytes)})
            return pdf_bytes, generated_path
        except Exception as e:
            logger.exception("Erro ao gerar PDF: %s", e)
            self._audit("pdf.error", {"error": str(e)})
            raise

    def sign_or_hash(
        self, data_bytes: bytes, filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        """Assina ou gera o hash SHA-256 do conteúdo e retorna metadados.

        Se `filepath` for fornecido e `ToolAssinatura` expõe calcular_hash_documento,
        usaremos a implementação da ferramenta; caso contrário, calculamos SHA-256 sobre bytes.
        """
        try:
            # If signing tool exists and accepts filepath/hash, prefer it
            if (
                self.signing
                and filepath
                and hasattr(self.signing, "calcular_hash_documento")
            ):
                try:
                    sha = self.signing.calcular_hash_documento(filepath)
                    self._audit("signing.tool_hash", {"sha256": sha})
                    return {"method": "tool", "sha256": sha}
                except Exception:
                    logger.exception(
                        "SigningTool.calcular_hash_documento falhou, fallback para SHA-256"
                    )

            # fallback SHA-256 on bytes
            digest = hashlib.sha256(data_bytes).hexdigest()
            self._audit("signing.sha256", {"sha256": digest})
            return {"method": "sha256", "sha256": digest}
        except Exception as e:
            logger.exception("Erro em sign_or_hash: %s", e)
            self._audit("signing.error", {"error": str(e)})
            raise

    # --- BaseAgent compatibility methods ---
    def process(self, input_data: dict, context: Optional[dict] = None) -> dict:
        """Compatibility wrapper implementing `BaseAgent.process`.

        Delegates to `processar_pedido` which implements the full flow.
        """
        try:
            return self.processar_pedido(input_data or {}, meta=context or {})
        except Exception as e:
            logger.exception("AgenteContabil.process failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "name": "Agente Contábil",
            "version": "1.0.0",
            "description": "Agente especialista em cálculos trabalhistas.",
        }

    def processar_pedido(
        self, dados_input: Dict[str, Any], meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Fluxo principal: calcular -> gerar PDF -> assinar/hash -> retorno com metadados.

        Retorna dict com chaves: success, resultado_calculo, pdf (bytes base64 opcional), assinatura
        """
        meta = meta or {}
        try:
            self._audit(
                "process.start",
                {"received_keys": list(dados_input.keys()), "meta": meta},
            )

            resultado_calculo = self.calcular(dados_input)

            pdf_bytes, pdf_path = self.gerar_pdf(
                resultado_calculo,
                meta={**meta, "generated_at": datetime.now(UTC).isoformat()},
            )

            signature = self.sign_or_hash(pdf_bytes, filepath=pdf_path)

            # Optionally avoid returning raw bytes in API responses; provide length and signature
            response = {
                "success": True,
                "resultado": resultado_calculo,
                "pdf_info": {"size": len(pdf_bytes), "path": pdf_path},
                "assinatura": signature,
            }

            self._audit(
                "process.end",
                {"success": True, "assinatura_method": signature.get("method")},
            )
            return response
        except Exception as e:
            logger.exception("Falha no processamento do pedido: %s", e)
            self._audit("process.error", {"error": str(e)})
            return {"success": False, "error": str(e)}
