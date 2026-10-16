"""
Tasks Assíncronas - Jobs de Processamento
Integra Cálculos, PDFs e Assinaturas em Jobs Assíncronos

Funcionalidades:
- Processamento de folha de pagamento
- Geração de SPED
- Processamento de vencimentos
- Geração de documentos com assinatura
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from celery import chain
from infra.job_state import JobStateManager
from infra.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="infra.tasks.processar_folha_pagamento",
    max_retries=3,
    default_retry_delay=60,
)
def processar_folha_pagamento(
    self,
    empresa_id: str,
    mes: int,
    ano: int,
    funcionarios: List[Dict],
) -> Dict:
    """
    Processa folha de pagamento completa para uma empresa

    Args:
        empresa_id: ID da empresa
        mes: Mês de referência
        ano: Ano de referência
        funcionarios: Lista de funcionários com dados

    Returns:
        Dicionário com resultados do processamento
    """
    state_manager = JobStateManager()
    task_id = self.request.id

    try:
        # Atualiza estado
        state_manager.update_state(
            task_id,
            status="PROCESSING",
            progress=10,
            message="Iniciando processamento da folha",
        )

        # Importa serviços necessários
        from services.calculation_service import CalculationService
        from services.document_service import DocumentService
        from services.evidence_service import GerenciadorEvidencias
        from services.signature_service import SignatureService

        calc_service = CalculationService()
        doc_service = DocumentService()
        sig_service = SignatureService()
        evidencias = GerenciadorEvidencias()

        resultados = []
        total_funcionarios = len(funcionarios)

        for idx, funcionario in enumerate(funcionarios):
            # Atualiza progresso
            progresso = 10 + int((idx / total_funcionarios) * 70)
            state_manager.update_state(
                task_id,
                progress=progresso,
                message=f"Processando funcionário {idx + 1}/{total_funcionarios}",
            )
            state_manager.add_log(
                task_id,
                "INFO",
                f"Processando: {funcionario.get('nome', 'N/A')}",
            )

            try:
                # 1. Calcula folha
                calculo = calc_service.calcular_salario(
                    salario_base=Decimal(str(funcionario["salario_base"])),
                    descontos=funcionario.get("descontos", {}),
                    beneficios=funcionario.get("beneficios", {}),
                )

                # 2. Gera PDF do holerite
                dados_holerite = {
                    "empresa_id": empresa_id,
                    "funcionario": funcionario,
                    "mes": mes,
                    "ano": ano,
                    "calculo": calculo,
                }

                pdf_path = doc_service.gerar_holerite(dados_holerite)

                # 3. Assina digitalmente
                if funcionario.get("requer_assinatura", True):
                    pdf_assinado = sig_service.assinar_pdf(
                        pdf_path,
                        certificado=funcionario.get("certificado"),
                    )
                else:
                    pdf_assinado = pdf_path

                # 4. Registra evidência
                evidencias.registrar_evidencia(
                    tipo="folha_pagamento",
                    descricao=f"Folha processada: {funcionario['nome']} - {mes}/{ano}",
                    dados={
                        "empresa_id": empresa_id,
                        "funcionario_id": funcionario.get("id"),
                        "mes": mes,
                        "ano": ano,
                        "salario_liquido": str(calculo["salario_liquido"]),
                    },
                    arquivo_relacionado=pdf_assinado,
                )

                resultados.append(
                    {
                        "funcionario_id": funcionario.get("id"),
                        "nome": funcionario["nome"],
                        "status": "success",
                        "pd": pdf_assinado,
                        "salario_liquido": str(calculo["salario_liquido"]),
                    }
                )

            except Exception as e:
                logger.error(
                    f"Erro ao processar funcionário {funcionario.get('nome')}: {e}"
                )
                resultados.append(
                    {
                        "funcionario_id": funcionario.get("id"),
                        "nome": funcionario["nome"],
                        "status": "error",
                        "error": str(e),
                    }
                )

        # Atualiza estado final
        state_manager.update_state(
            task_id,
            status="SUCCESS",
            progress=100,
            message="Folha processada com sucesso",
            metadata={"total_processados": len(resultados)},
        )

        return {
            "empresa_id": empresa_id,
            "mes": mes,
            "ano": ano,
            "total_funcionarios": total_funcionarios,
            "resultados": resultados,
            "processado_em": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Erro no processamento de folha: {e}")
        state_manager.update_state(
            task_id,
            status="FAILED",
            message=f"Erro: {str(e)}",
        )

        # Retry automático
        raise self.retry(exc=e, countdown=60)


@celery_app.task(
    bind=True,
    name="infra.tasks.gerar_sped",
    max_retries=3,
    default_retry_delay=120,
)
def gerar_sped(
    self,
    empresa_id: str,
    tipo_sped: str,
    periodo_inicio: str,
    periodo_fim: str,
    dados: Dict,
) -> Dict:
    """
    Gera arquivo SPED (Contábil, Fiscal, etc.)

    Args:
        empresa_id: ID da empresa
        tipo_sped: Tipo de SPED (CONTABIL, FISCAL, CONTRIBUICOES)
        periodo_inicio: Data início (ISO)
        periodo_fim: Data fim (ISO)
        dados: Dados para geração do SPED

    Returns:
        Caminho do arquivo SPED gerado
    """
    state_manager = JobStateManager()
    task_id = self.request.id

    try:
        state_manager.update_state(
            task_id,
            progress=10,
            message=f"Iniciando geração SPED {tipo_sped}",
        )

        from services.evidence_service import GerenciadorEvidencias
        from services.fiscal_service import FiscalService, TipoArquivoFiscal

        fiscal_service = FiscalService()
        evidencias = GerenciadorEvidencias()

        # Mapeia tipo
        tipos_map = {
            "CONTABIL": TipoArquivoFiscal.SPED_CONTABIL,
            "FISCAL": TipoArquivoFiscal.SPED_CONTABIL,  # Exemplo
            "DCTF": TipoArquivoFiscal.DCTF,
            "DIRF": TipoArquivoFiscal.DIRF,
        }

        tipo_arquivo = tipos_map.get(tipo_sped)
        if not tipo_arquivo:
            raise ValueError(f"Tipo SPED inválido: {tipo_sped}")

        state_manager.update_state(task_id, progress=30, message="Gerando arquivo...")

        # Gera SPED
        inicio = datetime.fromisoformat(periodo_inicio)
        fim = datetime.fromisoformat(periodo_fim)

        caminho_sped = fiscal_service.gerar_arquivo_fiscal(
            tipo=tipo_arquivo,
            dados=dados,
            periodo=(inicio, fim),
        )

        state_manager.update_state(task_id, progress=70, message="Validando arquivo...")

        # Valida
        validacao = fiscal_service.validar_arquivo_fiscal(tipo_arquivo, caminho_sped)

        # Registra evidência
        evidencias.registrar_evidencia(
            tipo=f"sped_{tipo_sped.lower()}",
            descricao=f"SPED {tipo_sped} gerado para {empresa_id}",
            dados={
                "empresa_id": empresa_id,
                "tipo": tipo_sped,
                "periodo": f"{periodo_inicio} a {periodo_fim}",
                "validacao": validacao,
            },
            arquivo_relacionado=caminho_sped,
        )

        state_manager.update_state(
            task_id,
            progress=100,
            message="SPED gerado com sucesso",
        )

        return {
            "empresa_id": empresa_id,
            "tipo_sped": tipo_sped,
            "arquivo": caminho_sped,
            "validacao": validacao,
            "gerado_em": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Erro ao gerar SPED: {e}")
        state_manager.update_state(task_id, status="FAILED", message=str(e))
        raise self.retry(exc=e, countdown=120)


@celery_app.task(
    bind=True,
    name="infra.tasks.processar_vencimentos",
    max_retries=2,
)
def processar_vencimentos(self, data_referencia: str) -> Dict:
    """
    Processa vencimentos do dia (boletos, impostos, etc.)

    Args:
        data_referencia: Data de referência (ISO)

    Returns:
        Lista de vencimentos processados
    """
    state_manager = JobStateManager()
    task_id = self.request.id

    try:
        state_manager.update_state(
            task_id,
            progress=10,
            message="Buscando vencimentos do dia",
        )

        # Importa serviços
        from services.evidence_service import GerenciadorEvidencias
        from services.financial_service import FinancialService

        FinancialService()
        evidencias = GerenciadorEvidencias()

        datetime.fromisoformat(data_referencia)

        # Simula busca de vencimentos (em produção, viria do banco)
        vencimentos = [
            {"tipo": "boleto", "valor": "1500.00", "descricao": "Fornecedor XYZ"},
            {"tipo": "imposto", "valor": "3200.00", "descricao": "DAS MEI"},
        ]

        processados = []
        for idx, venc in enumerate(vencimentos):
            progresso = 10 + int((idx / len(vencimentos)) * 80)
            state_manager.update_state(
                task_id,
                progress=progresso,
                message=f"Processando vencimento {idx + 1}/{len(vencimentos)}",
            )

            # Processa vencimento (exemplo)
            processados.append(
                {
                    "tipo": venc["tipo"],
                    "valor": venc["valor"],
                    "status": "notificado",
                }
            )

        # Registra evidência
        evidencias.registrar_evidencia(
            tipo="vencimentos_diarios",
            descricao=f"Vencimentos processados: {data_referencia}",
            dados={
                "data": data_referencia,
                "total": len(processados),
                "vencimentos": processados,
            },
        )

        state_manager.update_state(
            task_id,
            progress=100,
            message="Vencimentos processados",
        )

        return {
            "data": data_referencia,
            "total": len(processados),
            "vencimentos": processados,
        }

    except Exception as e:
        logger.error(f"Erro ao processar vencimentos: {e}")
        raise self.retry(exc=e)


@celery_app.task(name="infra.tasks.exemplo_workflow_complexo")
def exemplo_workflow_complexo(empresa_id: str, mes: int, ano: int) -> Dict:
    """
    Workflow complexo encadeado: Folha → SPED → Vencimentos
    Demonstra uso de chain e group do Celery
    """
    # Cria workflow encadeado
    workflow = chain(
        processar_folha_pagamento.s(
            empresa_id=empresa_id,
            mes=mes,
            ano=ano,
            funcionarios=[],  # Seria buscado do banco
        ),
        gerar_sped.s(
            empresa_id=empresa_id,
            tipo_sped="CONTABIL",
            periodo_inicio=f"{ano}-{mes:02d}-01",
            periodo_fim=f"{ano}-{mes:02d}-28",
            dados={},
        ),
    )

    # Executa workflow
    result = workflow.apply_async()

    return {
        "workflow_id": result.id,
        "status": "PENDING",
        "message": "Workflow iniciado",
    }
