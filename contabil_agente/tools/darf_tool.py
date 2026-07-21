"""
ToolDARF - Geração de DARF (Documento de Arrecadação Federal)
Gera guias para pagamento de impostos federais
"""

import json
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict

from core.config import Config
from utils.audit import send_audit


class ToolDARF:
    """
    Ferramenta para geração de DARF

    Códigos comuns:
    - 0561: IRRF (Imposto de Renda Retido na Fonte)
    - 8109: PIS
    - 2172: COFINS
    - 2469: CSLL (Contribuição Social sobre Lucro Líquido)
    - 0190: IRPJ (Imposto de Renda Pessoa Jurídica)
    - 6015: Simples Nacional
    """

    def __init__(self):
        """Inicializa gerador de DARF"""
        base_docs = getattr(Config, "DOCUMENTS_DIR", None)
        if not base_docs:
            base_docs = Path.cwd()
        self.darfs_dir = Path(base_docs) / "guias" / "darf"
        self.darfs_dir.mkdir(parents=True, exist_ok=True)

        # Códigos DARF
        self.codigos_darf = {
            "0561": "IRRF - Imposto de Renda Retido na Fonte",
            "8109": "PIS - Programa de Integração Social",
            "2172": "COFINS - Contribuição para Financiamento da Seguridade Social",
            "2469": "CSLL - Contribuição Social sobre Lucro Líquido",
            "0190": "IRPJ - Imposto de Renda Pessoa Jurídica",
            "6015": "Simples Nacional - DAS",
            "0211": "IRPJ - Lucro Presumido",
            "2089": "Contribuição Previdenciária sobre Receita Bruta",
        }

        send_audit("ToolDARF inicializado", level="info", context={})

    def calcular_vencimento_darf(self, competencia: str, codigo: str) -> str:
        """
        Calcula vencimento da DARF baseado na competência e código

        Args:
            competencia: MM/AAAA
            codigo: Código da DARF

        Returns:
            Data de vencimento (DD/MM/AAAA)
        """
        try:
            mes, ano = competencia.split("/")
            data_base = datetime(int(ano), int(mes), 1)

            # Regras de vencimento
            if codigo in ["0561", "8109", "2172"]:
                # IRRF, PIS, COFINS: dia 20 do mês seguinte
                mes_vencimento = data_base + timedelta(days=32)
                dia_vencimento = 20
            elif codigo in ["6015"]:
                # Simples Nacional: dia 20 do mês seguinte
                mes_vencimento = data_base + timedelta(days=32)
                dia_vencimento = 20
            else:
                # Padrão: último dia útil do mês seguinte
                mes_vencimento = data_base + timedelta(days=32)
                dia_vencimento = mes_vencimento.replace(day=28).day

            data_vencimento = mes_vencimento.replace(day=dia_vencimento)
            return data_vencimento.strftime("%d/%m/%Y")

        except Exception:
            return "20/01/2026"

    def _calcular_multa_juros_automatico(self, data_vencimento: str, principal: Decimal) -> tuple[Decimal, Decimal]:
        """Calcula multa e juros quando a guia estiver vencida.

        - Multa: 0.33% ao dia, limitada a 20% do principal.
        - Juros: usa taxa SELIC anual placeholder (10% a.a.) calculada de forma simples diária.
        """
        try:
            venc = datetime.strptime(data_vencimento, "%d/%m/%Y")
            hoje = datetime.now()
            dias = max(0, (hoje.date() - venc.date()).days)

            if dias <= 0:
                return (Decimal("0.00"), Decimal("0.00"))

            # multa diária 0.33%
            multa_diaria = Decimal("0.0033")
            multa = (principal * multa_diaria * Decimal(dias)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            limite_multa = (principal * Decimal("0.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if multa > limite_multa:
                multa = limite_multa

            # juros: SELIC placeholder 10% a.a., juros simples diário
            selic_anual = Decimal("0.10")
            juros_diario = (selic_anual / Decimal("365"))
            juros = (principal * juros_diario * Decimal(dias)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            return (multa, juros)
        except Exception:
            return (Decimal("0.00"), Decimal("0.00"))

    def gerar_darf(
        self,
        codigo_receita: str,
        competencia: str,
        valor_principal: Any,
        valor_multa: Any = 0,
        valor_juros: Any = 0,
        cnpj: str = "",
        razao_social: str = "",
    ) -> Dict[str, Any]:
        """
        Gera DARF para pagamento de imposto federal

        Args:
            codigo_receita: Código da receita (ex: 0561, 8109)
            competencia: MM/AAAA
            valor_principal: Valor principal do imposto
            valor_multa: Multa (se houver)
            valor_juros: Juros (se houver)
            cnpj: CNPJ do contribuinte
            razao_social: Razão social

        Returns:
            Dict com dados da DARF
        """
        send_audit(
            "Gerando DAR",
            level="info",
            context={
                "codigo": codigo_receita,
                "competencia": competencia,
                "valor": float(valor_principal),
            },
        )

        try:
            principal = Decimal(str(valor_principal)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            multa = Decimal(str(valor_multa)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            juros = Decimal(str(valor_juros)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Total
            valor_total = principal + multa + juros
            # Validações
            if valor_total <= 0:
                return {
                    "status": "error",
                    "message": "Valor da DARF deve ser maior que zero",
                }

            # Regra fiscal: valor mínimo para emissão de DARF
            if valor_total < Decimal("10.00"):
                return {
                    "status": "error",
                    "message": "Valor mínimo para DARF é R$ 10,00",
                }

            # Se multa/juros não foram informados e a data de vencimento já passou,
            # calcular automaticamente multas e juros básicos (placeholder SELIC).
            if multa == Decimal("0.00") and juros == Decimal("0.00"):
                try:
                    data_vencimento = self.calcular_vencimento_darf(competencia, codigo_receita)
                    calc_multa, calc_juros = self._calcular_multa_juros_automatico(data_vencimento, principal)
                    if calc_multa > 0 or calc_juros > 0:
                        multa = (multa + calc_multa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        juros = (juros + calc_juros).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        valor_total = principal + multa + juros
                except Exception:
                    pass

            if codigo_receita not in self.codigos_darf:
                send_audit(
                    f"Código DARF {codigo_receita} não encontrado na tabela",
                    level="warning",
                    context={},
                )
                descricao = f"Código {codigo_receita}"
            else:
                descricao = self.codigos_darf[codigo_receita]

            # Calcula vencimento
            data_vencimento = self.calcular_vencimento_darf(competencia, codigo_receita)

            # Gera identificador único
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            darf_id = (
                f"DARF_{codigo_receita}_{competencia.replace('/', '')}_{timestamp}"
            )

            # Dados da DARF
            darf_data = {
                "darf_id": darf_id,
                "codigo_receita": codigo_receita,
                "descricao": descricao,
                "competencia": competencia,
                "cnpj": cnpj,
                "razao_social": razao_social,
                "valores": {
                    "principal": principal,
                    "multa": multa,
                    "juros": juros,
                    "total": valor_total,
                },
                "data_vencimento": data_vencimento,
                "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "status": "pendente",
            }

            # Salva em arquivo JSON
            darf_file = self.darfs_dir / f"{darf_id}.json"
            with open(darf_file, "w", encoding="utf-8") as f:
                json.dump(darf_data, f, indent=2, ensure_ascii=False, default=str)

            send_audit(
                "DARF gerada com sucesso",
                level="info",
                context={"darf_id": darf_id, "valor_total": float(valor_total)},
            )

            return {
                "status": "success",
                "darf_id": darf_id,
                "codigo_receita": codigo_receita,
                "descricao": descricao,
                "competencia": competencia,
                "valor_principal": principal,
                "valor_multa": multa,
                "valor_juros": juros,
                "valor_total": valor_total,
                "vencimento": data_vencimento,
                "filepath": str(darf_file),
                "message": "DARF gerada com sucesso",
                "instrucoes": [
                    "1. Acesse o site da Receita Federal (receita.gov.br)",
                    "2. Selecione 'Emitir DARF'",
                    f"3. Código da Receita: {codigo_receita}",
                    f"4. Competência: {competencia}",
                    f"5. Valor Principal: R$ {principal:,.2f}",
                    f"6. Multa: R$ {multa:,.2f}" if multa > 0 else None,
                    f"7. Juros: R$ {juros:,.2f}" if juros > 0 else None,
                    f"8. Total a Pagar: R$ {valor_total:,.2f}",
                    f"9. Vencimento: {data_vencimento}",
                    "10. Gere o código de barras e pague até o vencimento",
                ],
            }

        except Exception as e:
            send_audit(f"Erro ao gerar DARF: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro ao gerar DARF: {str(e)}"}

    def gerar_darf_irrf(
        self, competencia: str, valor_irrf: Any, cnpj: str, razao_social: str
    ) -> Dict[str, Any]:
        """
        Gera DARF específica para IRRF

        Args:
            competencia: MM/AAAA
            valor_irrf: Valor do IRRF retido
            cnpj: CNPJ da empresa
            razao_social: Razão social

        Returns:
            Dict com DARF gerada
        """
        return self.gerar_darf(
            codigo_receita="0561",
            competencia=competencia,
            valor_principal=valor_irrf,
            cnpj=cnpj,
            razao_social=razao_social,
        )

    def gerar_darf_pis_cofins(
        self,
        competencia: str,
        valor_pis: Any,
        valor_cofins: Any,
        cnpj: str,
        razao_social: str,
    ) -> Dict[str, Any]:
        """
        Gera DARFs para PIS e COFINS

        Args:
            competencia: MM/AAAA
            valor_pis: Valor do PIS
            valor_cofins: Valor do COFINS
            cnpj: CNPJ
            razao_social: Razão social

        Returns:
            Dict com ambas DARFs
        """
        try:
            # DARF PIS
            darf_pis = self.gerar_darf(
                codigo_receita="8109",
                competencia=competencia,
                valor_principal=valor_pis,
                cnpj=cnpj,
                razao_social=razao_social,
            )

            # DARF COFINS
            darf_cofins = self.gerar_darf(
                codigo_receita="2172",
                competencia=competencia,
                valor_principal=valor_cofins,
                cnpj=cnpj,
                razao_social=razao_social,
            )

            return {
                "status": "success",
                "darf_pis": darf_pis,
                "darf_cofins": darf_cofins,
                "total_tributos": Decimal(str(valor_pis)) + Decimal(str(valor_cofins)),
                "message": "DARFs PIS e COFINS geradas",
            }

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def marcar_como_paga(
        self, darf_id: str, data_pagamento: str, numero_recibo: str = ""
    ) -> Dict[str, Any]:
        """
        Marca DARF como paga

        Args:
            darf_id: ID da DARF
            data_pagamento: DD/MM/AAAA
            numero_recibo: Número do recibo de pagamento

        Returns:
            Dict com status
        """
        try:
            darf_file = self.darfs_dir / f"{darf_id}.json"

            if not darf_file.exists():
                return {"status": "error", "message": "DARF não encontrada"}

            with open(darf_file, "r", encoding="utf-8") as f:
                darf_data = json.load(f)

            darf_data["status"] = "paga"
            darf_data["data_pagamento"] = data_pagamento
            darf_data["numero_recibo"] = numero_recibo

            with open(darf_file, "w", encoding="utf-8") as f:
                json.dump(darf_data, f, indent=2, ensure_ascii=False, default=str)

            send_audit(
                f"DARF {darf_id} marcada como paga",
                level="info",
                context={"data_pagamento": data_pagamento, "recibo": numero_recibo},
            )

            return {"status": "success", "message": "DARF marcada como paga"}

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def listar_darfs_pendentes(
        self, mes_competencia: str = None, codigo_receita: str = None
    ) -> list[Dict[str, Any]]:
        """
        Lista DARFs pendentes de pagamento

        Args:
            mes_competencia: Filtro opcional (MM/AAAA)
            codigo_receita: Filtro opcional de código

        Returns:
            Lista de DARFs pendentes
        """
        try:
            pendentes = []

            for darf_file in self.darfs_dir.glob("*.json"):
                with open(darf_file, "r", encoding="utf-8") as f:
                    darf_data = json.load(f)

                # Filtra pendentes
                if darf_data.get("status") != "pendente":
                    continue

                # Filtros opcionais
                if mes_competencia and darf_data.get("competencia") != mes_competencia:
                    continue

                if codigo_receita and darf_data.get("codigo_receita") != codigo_receita:
                    continue

                valores = darf_data.get("valores", {})
                pendentes.append(
                    {
                        "darf_id": darf_data.get("darf_id"),
                        "codigo": darf_data.get("codigo_receita"),
                        "descricao": darf_data.get("descricao"),
                        "competencia": darf_data.get("competencia"),
                        "valor_total": Decimal(str(valores.get("total", 0))),
                        "vencimento": darf_data.get("data_vencimento"),
                        "empresa": darf_data.get("razao_social"),
                    }
                )

            # Ordena por vencimento
            pendentes.sort(key=lambda x: x["vencimento"])

            return pendentes

        except Exception as e:
            send_audit(f"Erro ao listar DARFs: {e}", level="error", context={})
            return []
