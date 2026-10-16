"""
ToolAdmissao - Checklist de admissão de funcionários
Gerencia processo completo de admissão (ASO, eSocial, CTPS, etc)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    from contabil_agente.core.config import Config
except ImportError:
    from core.config import Config
try:
    from contabil_agente.utils.audit import send_audit
except ImportError:
    from utils.audit import send_audit


class ToolAdmissao:
    """
    Ferramenta para processo de admissão de funcionários

    Checklist completo:
    - Documentação pessoal
    - ASO (Atestado de Saúde Ocupacional)
    - eSocial S-2200 (Admissão)
    - Registro na CTPS
    - Cadastro de benefícios
    - Integração ao departamento
    """

    def __init__(self):
        """Inicializa ferramenta de admissão"""
        self.admissoes_dir = Path(Config.DOCUMENTS_DIR) / "admissoes"
        self.admissoes_dir.mkdir(parents=True, exist_ok=True)

        # Checklist padrão de documentos
        self.documentos_obrigatorios = [
            "RG ou CNH (original e cópia)",
            "CPF (original e cópia)",
            "Título de Eleitor (se aplicável)",
            "Certidão de Nascimento ou Casamento",
            "Comprovante de Residência (até 3 meses)",
            "Carteira de Trabalho (CTPS)",
            "PIS/PASEP (se já tiver)",
            "Certificado de Reservista (homens)",
            "Cartão do SUS",
            "Foto 3x4 (2 vias)",
            "Certidão de Nascimento dos filhos (se houver)",
            "Carteira de Vacinação dos filhos menores de 7 anos",
            "Comprovante de escolaridade",
            "Dados bancários (para depósito)",
        ]

        # Etapas do processo
        self.etapas_admissao = [
            "Triagem de documentos",
            "Exame médico admissional (ASO)",
            "Cadastro no eSocial (S-2200)",
            "Registro em CTPS (físico ou digital)",
            "Cadastro de benefícios (VT, VR, VA, plano de saúde)",
            "Entrega de EPI (se aplicável)",
            "Integração e treinamento inicial",
            "Assinatura de contrato de trabalho",
            "Entrega de crachá e controle de ponto",
        ]

        send_audit("ToolAdmissao inicializado", level="info", context={})

    def criar_processo_admissao(
        self, dados_funcionario: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Cria novo processo de admissão

        Args:
            dados_funcionario: Dict com dados do funcionário
                - nome
                - cpf
                - cargo
                - data_admissao
                - salario
                - departamento
                - contato (email, telefone)

        Returns:
            Dict com ID do processo e checklist
        """
        send_audit(
            "Criando processo de admissão",
            level="info",
            context={"funcionario": dados_funcionario.get("nome")},
        )

        try:
            # Basic validations for required fields
            cpf_raw = dados_funcionario.get("cp") or dados_funcionario.get("cpf")
            cargo = dados_funcionario.get("cargo")
            data_admissao_raw = dados_funcionario.get("data_admissao")

            if not cpf_raw or not str(cpf_raw).strip():
                return {"status": "error", "message": "CPF ausente"}
            if not cargo or not str(cargo).strip():
                return {"status": "error", "message": "Cargo ausente"}
            if not data_admissao_raw or not str(data_admissao_raw).strip():
                return {"status": "error", "message": "data_admissao ausente"}

            # Clean CPF (remove punctuation)
            cpf_limpo = str(cpf_raw).replace(".", "").replace("-", "").strip()

            # Normalize data_admissao to ISO date (YYYY-MM-DD) when possible
            data_admissao_iso = data_admissao_raw
            try:
                # Accept dd/mm/YYYY or ISO formats
                if isinstance(data_admissao_raw, str) and "/" in data_admissao_raw:
                    dt = datetime.strptime(data_admissao_raw, "%d/%m/%Y")
                    data_admissao_iso = dt.date().isoformat()
                else:
                    # Try ISO parse
                    dt = datetime.fromisoformat(str(data_admissao_raw))
                    data_admissao_iso = dt.date().isoformat()
            except Exception:
                # If cannot parse, return error
                return {"status": "error", "message": "data_admissao inválida"}

            # Age validation if date of birth provided
            data_nasc_raw = dados_funcionario.get("data_nascimento")
            if data_nasc_raw:
                try:
                    if isinstance(data_nasc_raw, str) and "/" in data_nasc_raw:
                        nasc_dt = datetime.strptime(data_nasc_raw, "%d/%m/%Y").date()
                    else:
                        nasc_dt = datetime.fromisoformat(str(data_nasc_raw)).date()

                    today = datetime.now().date()
                    if nasc_dt > today:
                        return {"status": "error", "message": "data_nascimento futura"}
                    age = (
                        today.year
                        - nasc_dt.year
                        - ((today.month, today.day) < (nasc_dt.month, nasc_dt.day))
                    )
                    if age < 14:
                        return {"status": "error", "message": "idade menor que 14 anos"}
                except Exception:
                    return {"status": "error", "message": "data_nascimento inválida"}
            # Gera ID do processo (usa cpf_limpo já calculado)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            processo_id = f"ADM_{cpf_limpo}_{timestamp}"

            # Cria checklist
            checklist = []
            for doc in self.documentos_obrigatorios:
                checklist.append({"item": doc, "status": "pendente", "observacao": ""})

            # Cria etapas
            etapas = []
            for etapa in self.etapas_admissao:
                etapas.append(
                    {
                        "etapa": etapa,
                        "status": "pendente",
                        "data_conclusao": None,
                        "responsavel": "",
                    }
                )

            # Dados do processo
            processo_data = {
                "processo_id": processo_id,
                "status_geral": "em_andamento",
                "funcionario": {
                    "nome": dados_funcionario.get("nome", ""),
                    "cp": cpf_limpo,
                    "cargo": dados_funcionario.get("cargo", ""),
                    "data_admissao": data_admissao_iso,
                    "salario": str(dados_funcionario.get("salario", "")),
                    "departamento": dados_funcionario.get("departamento", ""),
                    "contato": dados_funcionario.get("contato", {}),
                },
                "checklist_documentos": checklist,
                "etapas_processo": etapas,
                "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "pendencias": [],
                "observacoes": [],
            }

            # Salva processo
            processo_file = self.admissoes_dir / f"{processo_id}.json"
            with open(processo_file, "w", encoding="utf-8") as f:
                json.dump(processo_data, f, indent=2, ensure_ascii=False)

            send_audit(
                "Processo de admissão criado",
                level="info",
                context={
                    "processo_id": processo_id,
                    "funcionario": dados_funcionario.get("nome"),
                },
            )

            return {
                "status": "success",
                "processo_id": processo_id,
                "funcionario": dados_funcionario.get("nome"),
                "total_documentos": len(checklist),
                "total_etapas": len(etapas),
                "filepath": str(processo_file),
                "message": "Processo de admissão criado com sucesso",
                "proximos_passos": [
                    "1. Solicitar documentos ao funcionário",
                    "2. Agendar exame médico admissional",
                    "3. Preparar contrato de trabalho",
                    "4. Cadastrar no eSocial após ASO",
                ],
            }

        except Exception as e:
            send_audit(f"Erro ao criar processo: {e}", level="error", context={})
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def atualizar_documento(
        self, processo_id: str, item_documento: str, status: str, observacao: str = ""
    ) -> Dict[str, Any]:
        """
        Atualiza status de documento no checklist

        Args:
            processo_id: ID do processo
            item_documento: Nome do documento
            status: 'entregue' ou 'pendente'
            observacao: Observação opcional

        Returns:
            Dict com status
        """
        try:
            processo_file = self.admissoes_dir / f"{processo_id}.json"

            if not processo_file.exists():
                return {"status": "error", "message": "Processo não encontrado"}

            with open(processo_file, "r", encoding="utf-8") as f:
                processo_data = json.load(f)

            # Atualiza documento
            atualizado = False
            for doc in processo_data["checklist_documentos"]:
                if item_documento.lower() in doc["item"].lower():
                    doc["status"] = status
                    doc["observacao"] = observacao
                    atualizado = True
                    break

            if not atualizado:
                return {
                    "status": "error",
                    "message": "Documento não encontrado no checklist",
                }

            # Atualiza timestamp
            processo_data["atualizado_em"] = datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            )

            # Salva
            with open(processo_file, "w", encoding="utf-8") as f:
                json.dump(processo_data, f, indent=2, ensure_ascii=False)

            send_audit(
                f"Documento atualizado: {item_documento}",
                level="info",
                context={"processo_id": processo_id, "status": status},
            )

            return {
                "status": "success",
                "message": f"Documento '{item_documento}' atualizado",
            }

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def concluir_etapa(
        self, processo_id: str, etapa: str, responsavel: str = ""
    ) -> Dict[str, Any]:
        """
        Marca etapa como concluída

        Args:
            processo_id: ID do processo
            etapa: Nome da etapa
            responsavel: Nome do responsável

        Returns:
            Dict com status
        """
        try:
            processo_file = self.admissoes_dir / f"{processo_id}.json"

            if not processo_file.exists():
                return {"status": "error", "message": "Processo não encontrado"}

            with open(processo_file, "r", encoding="utf-8") as f:
                processo_data = json.load(f)

            # Atualiza etapa
            atualizado = False
            for etp in processo_data["etapas_processo"]:
                if etapa.lower() in etp["etapa"].lower():
                    etp["status"] = "concluida"
                    etp["data_conclusao"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    etp["responsavel"] = responsavel
                    atualizado = True
                    break

            if not atualizado:
                return {"status": "error", "message": "Etapa não encontrada"}

            # Verifica se todas as etapas foram concluídas
            todas_concluidas = all(
                etp["status"] == "concluida" for etp in processo_data["etapas_processo"]
            )

            if todas_concluidas:
                processo_data["status_geral"] = "concluido"
                send_audit(
                    f"Processo de admissão CONCLUÍDO: {processo_id}",
                    level="info",
                    context={},
                )

            # Atualiza timestamp
            processo_data["atualizado_em"] = datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            )

            # Salva
            with open(processo_file, "w", encoding="utf-8") as f:
                json.dump(processo_data, f, indent=2, ensure_ascii=False)

            return {
                "status": "success",
                "etapa_concluida": etapa,
                "todas_concluidas": todas_concluidas,
                "message": f"Etapa '{etapa}' concluída"
                + (" - Processo finalizado!" if todas_concluidas else ""),
            }

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def obter_status_processo(self, processo_id: str) -> Dict[str, Any]:
        """
        Obtém status completo do processo

        Args:
            processo_id: ID do processo

        Returns:
            Dict com status detalhado
        """
        try:
            processo_file = self.admissoes_dir / f"{processo_id}.json"

            if not processo_file.exists():
                return {"status": "error", "message": "Processo não encontrado"}

            with open(processo_file, "r", encoding="utf-8") as f:
                processo_data = json.load(f)

            # Calcula progresso
            docs_entregues = sum(
                1
                for doc in processo_data["checklist_documentos"]
                if doc["status"] == "entregue"
            )
            total_docs = len(processo_data["checklist_documentos"])

            etapas_concluidas = sum(
                1
                for etp in processo_data["etapas_processo"]
                if etp["status"] == "concluida"
            )
            total_etapas = len(processo_data["etapas_processo"])

            progresso_geral = (
                (docs_entregues + etapas_concluidas) / (total_docs + total_etapas) * 100
            )

            return {
                "status": "success",
                "processo_id": processo_id,
                "funcionario": processo_data["funcionario"]["nome"],
                "status_geral": processo_data["status_geral"],
                "progresso": {
                    "documentos": f"{docs_entregues}/{total_docs}",
                    "etapas": f"{etapas_concluidas}/{total_etapas}",
                    "percentual_geral": round(progresso_geral, 1),
                },
                "checklist_documentos": processo_data["checklist_documentos"],
                "etapas_processo": processo_data["etapas_processo"],
                "pendencias": [
                    doc["item"]
                    for doc in processo_data["checklist_documentos"]
                    if doc["status"] == "pendente"
                ],
                "proximas_etapas": [
                    etp["etapa"]
                    for etp in processo_data["etapas_processo"]
                    if etp["status"] == "pendente"
                ][
                    :3
                ],  # Próximas 3 etapas
            }

        except Exception as e:
            return {"status": "error", "message": f"Erro: {str(e)}"}

    def listar_admissoes_pendentes(self) -> List[Dict[str, Any]]:
        """
        Lista processos de admissão em andamento

        Returns:
            Lista de processos
        """
        try:
            processos = []

            for processo_file in self.admissoes_dir.glob("*.json"):
                with open(processo_file, "r", encoding="utf-8") as f:
                    processo_data = json.load(f)

                # Filtra apenas em andamento
                if processo_data.get("status_geral") == "concluido":
                    continue

                # Calcula progresso
                etapas_concluidas = sum(
                    1
                    for etp in processo_data["etapas_processo"]
                    if etp["status"] == "concluida"
                )
                total_etapas = len(processo_data["etapas_processo"])

                processos.append(
                    {
                        "processo_id": processo_data["processo_id"],
                        "funcionario": processo_data["funcionario"]["nome"],
                        "cargo": processo_data["funcionario"]["cargo"],
                        "data_admissao": processo_data["funcionario"]["data_admissao"],
                        "progresso": f"{etapas_concluidas}/{total_etapas}",
                        "criado_em": processo_data["criado_em"],
                    }
                )

            # Ordena por data de criação
            processos.sort(key=lambda x: x["criado_em"], reverse=True)

            return processos

        except Exception as e:
            send_audit(f"Erro ao listar admissões: {e}", level="error", context={})
            return []
