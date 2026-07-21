"""
ToolGPS - Geração de Guia da Previdência Social
Gera GPS para recolhimento de INSS
"""

import json
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict

try:
    from contabil_agente.core.config import Config
except ImportError:
    from core.config import Config
try:
    from contabil_agente.utils.audit import send_audit
except ImportError:
    from utils.audit import send_audit
from .rules_loader import RulesLoader, RuleNotFoundError


class ToolGPS:
    """
    Ferramenta para geração de GPS (Guia da Previdência Social)

    Códigos de pagamento:
    - 2100: Contribuinte Individual
    - 2011: Empresa (INSS Patronal)
    - 1007: Autônomo / Facultativo
    """

    def __init__(self):
        """Inicializa gerador de GPS"""
        self.guias_dir = Path(Config.DOCUMENTS_DIR) / "guias" / "gps"
        self.guias_dir.mkdir(parents=True, exist_ok=True)

        # Códigos de pagamento GPS
        self.codigos_gps = {
            "2100": "Contribuinte Individual - Recolhimento Mensal",
            "2011": "Empresa - INSS Patronal",
            "1007": "Contribuinte Individual - Autônomo",
            "1120": "Empregador Doméstico",
            "1147": "Facultativo Mensal",
        }

        send_audit("ToolGPS inicializado", level="info", context={})

        # Load normative rules (INSS ceiling, FGTS rates)
        try:
            rules_base = None
            try:
                docs = getattr(Config, "DOCUMENTS_DIR", None)
                if docs:
                    candidate = Path(str(docs)) / "rules"
                    if candidate.is_dir():
                        rules_base = str(candidate)
            except Exception:
                rules_base = None

            loader = RulesLoader(rules_dir=rules_base)
            rules = loader.load_all()

            # INSS ceiling
            ceiling = (
                rules.get("tax", {}).get("charges_and_fines", {}).get("ceiling_inss")
            )
            if ceiling is None:
                ceiling = (
                    rules.get("tax", {}).get("employee_inss_table", {}).get("ceiling")
                )
            if ceiling is None:
                raise RuleNotFoundError(
                    "Teto INSS não encontrado em rules/tax_rules.yaml"
                )
            self.inss_ceiling = Decimal(str(ceiling))

            # FGTS rates
            fgts = rules.get("tax", {}).get("charges_and_fines", {}).get("fgts", {})
            # The loader may return fractional values (0.08) or percent (8.00)
            fs = Decimal(str(fgts.get("standard_rate", "8.00")))
            if fs > 1:
                fs = fs / Decimal("100")
            self.fgts_standard_rate = fs

            fa = Decimal(str(fgts.get("apprentice_rate", "2.00")))
            if fa > 1:
                fa = fa / Decimal("100")
            self.fgts_apprentice_rate = fa

        except RuleNotFoundError:
            send_audit(
                "Rules missing or corrupted for GPS tool", level="error", context={}
            )
            raise
        except Exception:
            send_audit(
                "Unexpected error loading rules for GPS tool; continuing with defaults",
                level="warning",
                context={},
            )
            # Defaults
            self.inss_ceiling = Decimal("8157.41")
            self.fgts_standard_rate = Decimal("8.00")

    def calcular_vencimento(self, competencia: str) -> str:
        """
        Calcula data de vencimento da GPS

        Args:
            competencia: MM/AAAA

        Returns:
            Data de vencimento (DD/MM/AAAA)
        """
        try:
            mes, ano = competencia.split("/")
            # Vencimento: dia 20 do mês seguinte
            data_base = datetime(int(ano), int(mes), 1)
            mes_vencimento = data_base + timedelta(days=32)
            data_vencimento = mes_vencimento.replace(day=20)
            return data_vencimento.strftime("%d/%m/%Y")
        except Exception:
            return "20/01/2026"

    def gerar_gps(
        self,
        codigo_pagamento: str,
        competencia: str,
        valor: Any,
        identificador: str,
        nome_contribuinte: str,
        tipo_contribuinte: str = "empresa",
    ) -> Dict[str, Any]:
        """
        Gera GPS para recolhimento

        Args:
            codigo_pagamento: Código GPS (ex: 2100, 2011)
            competencia: MM/AAAA
            valor: Valor a recolher
            identificador: CNPJ ou CPF
            nome_contribuinte: Nome da empresa ou contribuinte
            tipo_contribuinte: 'empresa', 'individual', 'autonomo'

        Returns:
            Dict com dados da GPS
        """
        send_audit(
            "Gerando GPS",
            level="info",
            context={
                "codigo": codigo_pagamento,
                "competencia": competencia,
                "valor": float(valor),
            },
        )

        try:
            valor_gps = Decimal(str(valor)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Validações
            if valor_gps <= 0:
                return {
                    "status": "error",
                    "message": "Valor da GPS deve ser maior que zero",
                }

            if codigo_pagamento not in self.codigos_gps:
                return {
                    "status": "error",
                    "message": f"Código {codigo_pagamento} inválido",
                }

            # Calcula vencimento
            data_vencimento = self.calcular_vencimento(competencia)

            # Gera identificador único
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            gps_id = (
                f"GPS_{codigo_pagamento}_{competencia.replace('/', '')}_{timestamp}"
            )

            # Dados da GPS
            gps_data = {
                "gps_id": gps_id,
                "codigo_pagamento": codigo_pagamento,
                "descricao_codigo": self.codigos_gps[codigo_pagamento],
                "competencia": competencia,
                "identificador": identificador,  # CNPJ ou CPF
                "nome_contribuinte": nome_contribuinte,
                "tipo_contribuinte": tipo_contribuinte,
                "valor": valor_gps,
                "data_vencimento": data_vencimento,
                "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "status": "pendente",
            }

            # Salva em arquivo JSON
            gps_file = self.guias_dir / f"{gps_id}.json"
            with open(gps_file, "w", encoding="utf-8") as f:
                json.dump(gps_data, f, indent=2, ensure_ascii=False, default=str)

            send_audit(
                "GPS gerada com sucesso",
                level="info",
                context={"gps_id": gps_id, "valor": float(valor_gps)},
            )

            return {
                "status": "success",
                "gps_id": gps_id,
                "codigo_pagamento": codigo_pagamento,
                "descricao": self.codigos_gps[codigo_pagamento],
                "competencia": competencia,
                "valor": valor_gps,
                "vencimento": data_vencimento,
                "filepath": str(gps_file),
                "message": "GPS gerada com sucesso",
                "instrucoes": [
                    "1. Acesse o portal da Receita Federal ou banco credenciado",
                    f"2. Informe código de pagamento: {codigo_pagamento}",
                    f"3. Competência: {competencia}",
                    f"4. Valor: R$ {valor_gps:,.2f}",
                    f"5. Vencimento: {data_vencimento}",
                    "6. Gere o boleto ou pague via débito automático",
                ],
            }

        except Exception as e:
            send_audit(f"Erro ao gerar GPS: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro ao gerar GPS: {str(e)}"}

    def gerar_gps_empresa(
        self,
        cnpj: str,
        razao_social: str,
        competencia: str,
        valor_inss_patronal: Any,
        valor_inss_funcionarios: Any = 0,
    ) -> Dict[str, Any]:
        """
        Gera GPS específica para empresa

        Args:
            cnpj: CNPJ da empresa
            razao_social: Razão social
            competencia: MM/AAAA
            valor_inss_patronal: INSS patronal (20%)
            valor_inss_funcionarios: INSS descontado dos funcionários

        Returns:
            Dict com GPS gerada
        """
        try:
            patronal = Decimal(str(valor_inss_patronal))
            funcionarios = Decimal(str(valor_inss_funcionarios))
            total = patronal + funcionarios

            resultado = self.gerar_gps(
                codigo_pagamento="2011",
                competencia=competencia,
                valor=total,
                identificador=cnpj,
                nome_contribuinte=razao_social,
                tipo_contribuinte="empresa",
            )

            if resultado["status"] == "success":
                resultado["detalhamento"] = {
                    "inss_patronal": patronal,
                    "inss_funcionarios": funcionarios,
                    "total": total,
                }

            return resultado

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def marcar_como_paga(self, gps_id: str, data_pagamento: str) -> Dict[str, Any]:
        """
        Marca GPS como paga

        Args:
            gps_id: ID da GPS
            data_pagamento: DD/MM/AAAA

        Returns:
            Dict com status
        """
        try:
            gps_file = self.guias_dir / f"{gps_id}.json"

            if not gps_file.exists():
                return {"status": "error", "message": "GPS não encontrada"}

            with open(gps_file, "r", encoding="utf-8") as f:
                gps_data = json.load(f)

            gps_data["status"] = "paga"
            gps_data["data_pagamento"] = data_pagamento

            with open(gps_file, "w", encoding="utf-8") as f:
                json.dump(gps_data, f, indent=2, ensure_ascii=False, default=str)

            send_audit(
                f"GPS {gps_id} marcada como paga",
                level="info",
                context={"data_pagamento": data_pagamento},
            )

            return {"status": "success", "message": "GPS marcada como paga"}

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def listar_gps_pendentes(self, mes_competencia: str = None) -> list[Dict[str, Any]]:
        """
        Lista GPS pendentes de pagamento

        Args:
            mes_competencia: Filtro opcional (MM/AAAA)

        Returns:
            Lista de GPS pendentes
        """
        try:
            pendentes = []

            for gps_file in self.guias_dir.glob("*.json"):
                with open(gps_file, "r", encoding="utf-8") as f:
                    gps_data = json.load(f)

                # Filtra pendentes
                if gps_data.get("status") != "pendente":
                    continue

                # Filtra competência se especificado
                if mes_competencia and gps_data.get("competencia") != mes_competencia:
                    continue

                pendentes.append(
                    {
                        "gps_id": gps_data.get("gps_id"),
                        "codigo": gps_data.get("codigo_pagamento"),
                        "competencia": gps_data.get("competencia"),
                        "valor": Decimal(str(gps_data.get("valor", 0))),
                        "vencimento": gps_data.get("data_vencimento"),
                        "contribuinte": gps_data.get("nome_contribuinte"),
                    }
                )

            # Ordena por vencimento
            pendentes.sort(key=lambda x: x["vencimento"])

            return pendentes

        except Exception as e:
            send_audit(f"Erro ao listar GPS: {e}", level="error", context={})
            return []
