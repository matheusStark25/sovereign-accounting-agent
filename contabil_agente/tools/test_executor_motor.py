"""
Testes Unitários para o Motor de Execução Robótica
========================================================================================
Execução:
    pytest tools/test_executor_motor.py -v

    Ou com cobertura:
    pytest tools/test_executor_motor.py -v --cov=tools.executor_motor
========================================================================================
"""

import asyncio
import json
import sys
import pytest
from pathlib import Path
from datetime import datetime

from tools.executor_motor import (
    AccountingBot,
    SessionAuditoria,
    ElementoMapeado,
)

sys.path.insert(0, str(Path(__file__).parent.parent))


# ========================================================================================
# FIXTURES
# ========================================================================================


@pytest.fixture
def config_basica():
    """Configuração básica para testes"""
    return {
        "nome": "Teste Básico",
        "descricao": "Configuração para testes unitários",
        "acoes": [
            {
                "tipo": "goto",
                "url": "https://example.com",
            },
            {
                "tipo": "screenshot",
                "path": "teste.png",
            },
        ],
    }


@pytest.fixture
async def bot_instance():
    """Instância do bot para testes"""
    bot = AccountingBot(headless=True)
    await bot.inicializar()
    yield bot
    await bot.finalizar()


# ========================================================================================
# TESTES DE CLASSES DE DADOS
# ========================================================================================


def test_sessao_auditoria_criacao():
    """Testa criação de sessão de auditoria"""
    sessao = SessionAuditoria(
        tenant_id="TEST-001",
        session_id="session_test",
    )

    assert sessao.tenant_id == "TEST-001"
    assert sessao.session_id == "session_test"
    assert sessao.status == "em_andamento"
    assert sessao.total_acoes == 0
    assert sessao.acoes_sucesso == 0
    assert sessao.acoes_falha == 0


def test_sessao_auditoria_adicionar_log():
    """Testa adição de logs à sessão"""
    sessao = SessionAuditoria(
        tenant_id="TEST-001",
        session_id="session_test",
    )

    sessao.adicionar_log(
        acao="click",
        status="sucesso",
        detalhes={"selector": "#btn-test"},
    )

    assert sessao.total_acoes == 1
    assert sessao.acoes_sucesso == 1
    assert sessao.acoes_falha == 0
    assert len(sessao.logs) == 1
    assert sessao.logs[0]["acao"] == "click"


def test_sessao_auditoria_adicionar_log_erro():
    """Testa adição de log de erro"""
    sessao = SessionAuditoria(
        tenant_id="TEST-001",
        session_id="session_test",
    )

    sessao.adicionar_log(
        acao="fill",
        status="erro",
        detalhes={"error": "Element not found"},
    )

    assert sessao.total_acoes == 1
    assert sessao.acoes_sucesso == 0
    assert sessao.acoes_falha == 1


def test_sessao_auditoria_finalizar():
    """Testa finalização de sessão"""
    sessao = SessionAuditoria(
        tenant_id="TEST-001",
        session_id="session_test",
    )

    sessao.finalizar(status="concluido")

    assert sessao.status == "concluido"
    assert sessao.timestamp_fim is not None


def test_sessao_auditoria_para_dict():
    """Testa conversão de sessão para dicionário"""
    sessao = SessionAuditoria(
        tenant_id="TEST-001",
        session_id="session_test",
    )

    sessao.adicionar_log("goto", "sucesso")
    sessao.adicionar_log("click", "sucesso")
    sessao.finalizar()

    dict_sessao = sessao.para_dict()

    assert dict_sessao["tenant_id"] == "TEST-001"
    assert dict_sessao["total_acoes"] == 2
    assert dict_sessao["acoes_sucesso"] == 2
    assert dict_sessao["taxa_sucesso"] == 100.0
    assert dict_sessao["status"] == "concluido"


def test_elemento_mapeado_criacao():
    """Testa criação de elemento mapeado"""
    elemento = ElementoMapeado(
        tag_name="input",
        element_id="email",
        name="email",
        role="textbox",
        placeholder="Digite seu e-mail",
        is_visible=True,
        is_enabled=True,
    )

    assert elemento.tag_name == "input"
    assert elemento.element_id == "email"
    assert elemento.is_visible is True


def test_elemento_mapeado_para_dict():
    """Testa conversão de elemento para dicionário"""
    elemento = ElementoMapeado(
        tag_name="button",
        element_id="btn-submit",
        text="Enviar",
        selector_css="#btn-submit",
        is_visible=True,
        is_enabled=True,
    )

    dict_elemento = elemento.para_dict()

    assert dict_elemento["tag"] == "button"
    assert dict_elemento["id"] == "btn-submit"
    assert dict_elemento["text"] == "Enviar"
    assert dict_elemento["seletores"]["css"] == "#btn-submit"
    assert dict_elemento["estado"]["visivel"] is True


# ========================================================================================
# TESTES DE INICIALIZAÇÃO
# ========================================================================================


@pytest.mark.asyncio
async def test_bot_inicializacao():
    """Testa inicialização do bot"""
    bot = AccountingBot(headless=True)

    await bot.inicializar()

    assert bot._playwright is not None
    assert bot._browser is not None

    await bot.finalizar()


@pytest.mark.asyncio
async def test_bot_finalizacao():
    """Testa finalização do bot"""
    bot = AccountingBot(headless=True)

    await bot.inicializar()
    await bot.finalizar()

    # Após finalização, contextos devem estar vazios
    assert len(bot._contextos_ativos) == 0


# ========================================================================================
# TESTES DE CONTEXTOS (MULTI-TENANCY)
# ========================================================================================


@pytest.mark.asyncio
async def test_obter_contexto_novo(bot_instance):
    """Testa criação de novo contexto"""
    contexto = await bot_instance._obter_contexto("TENANT-001")

    assert contexto is not None
    assert "TENANT-001" in bot_instance._contextos_ativos


@pytest.mark.asyncio
async def test_obter_contexto_existente(bot_instance):
    """Testa reutilização de contexto existente"""
    contexto1 = await bot_instance._obter_contexto("TENANT-001")
    contexto2 = await bot_instance._obter_contexto("TENANT-001")

    # Deve retornar o mesmo contexto
    assert contexto1 is contexto2


@pytest.mark.asyncio
async def test_contextos_isolados(bot_instance):
    """Testa isolamento de contextos entre tenants"""
    contexto_a = await bot_instance._obter_contexto("TENANT-A")
    contexto_b = await bot_instance._obter_contexto("TENANT-B")

    # Devem ser contextos diferentes
    assert contexto_a is not contexto_b
    assert len(bot_instance._contextos_ativos) == 2


@pytest.mark.asyncio
async def test_fechar_contexto(bot_instance):
    """Testa fechamento de contexto específico"""
    await bot_instance._obter_contexto("TENANT-001")

    assert "TENANT-001" in bot_instance._contextos_ativos

    await bot_instance._fechar_contexto("TENANT-001")

    assert "TENANT-001" not in bot_instance._contextos_ativos


# ========================================================================================
# TESTES DE EXECUÇÃO DE FLUXOS
# ========================================================================================


@pytest.mark.asyncio
async def test_executar_fluxo_basico(bot_instance, config_basica):
    """Testa execução de fluxo básico"""
    resultado = await bot_instance.executar_fluxo(
        config=config_basica,
        tenant_id="TEST-001",
    )
    sessao = resultado.sessao

    assert sessao is not None
    assert sessao.tenant_id == "TEST-001"
    assert sessao.total_acoes >= 0
    assert sessao.status in ["concluido", "erro"]


@pytest.mark.asyncio
async def test_executar_fluxo_com_session_id(bot_instance, config_basica):
    """Testa execução com session_id customizado"""
    resultado = await bot_instance.executar_fluxo(
        config=config_basica,
        tenant_id="TEST-001",
        session_id="custom_session_123",
    )
    sessao = resultado.sessao

    assert sessao.session_id == "custom_session_123"


@pytest.mark.asyncio
async def test_executar_fluxo_gera_auditoria(bot_instance, config_basica):
    """Testa se execução gera arquivo de auditoria"""
    resultado = await bot_instance.executar_fluxo(
        config=config_basica,
        tenant_id="TEST-001",
    )
    sessao = resultado.sessao

    # Verificar se arquivo de auditoria existe
    auditoria_path = (
        bot_instance._logs_dir
        / f"auditoria_{sessao.tenant_id}_{sessao.session_id}.json"
    )
    assert auditoria_path.exists()


# ========================================================================================
# TESTES DE AÇÕES INDIVIDUAIS
# ========================================================================================


@pytest.mark.asyncio
async def test_acao_goto(bot_instance):
    """Testa ação goto"""
    contexto = await bot_instance._obter_contexto("TEST-GOTO")
    page = await contexto.new_page()

    sessao = SessionAuditoria(tenant_id="TEST-GOTO", session_id="test")

    acao = {
        "tipo": "goto",
        "url": "https://example.com",
    }

    await bot_instance._acao_goto(page, acao, sessao)

    assert page.url == "https://example.com/"

    await page.close()


@pytest.mark.asyncio
async def test_acao_screenshot(bot_instance):
    """Testa ação screenshot"""
    contexto = await bot_instance._obter_contexto("TEST-SCREENSHOT")
    page = await contexto.new_page()
    await page.goto("https://example.com")

    sessao = SessionAuditoria(tenant_id="TEST-SCREENSHOT", session_id="test")

    acao = {
        "tipo": "screenshot",
        "path": "test_screenshot.png",
    }

    await bot_instance._acao_screenshot(page, acao, sessao)

    screenshot_path = bot_instance._screenshots_dir / "test_screenshot.png"
    assert screenshot_path.exists()

    # Limpar
    screenshot_path.unlink()
    await page.close()


@pytest.mark.asyncio
async def test_acao_wait_tempo(bot_instance):
    """Testa ação wait com tempo fixo"""
    contexto = await bot_instance._obter_contexto("TEST-WAIT")
    page = await contexto.new_page()

    sessao = SessionAuditoria(tenant_id="TEST-WAIT", session_id="test")

    acao = {
        "tipo": "wait",
        "tempo": 1000,  # 1 segundo
    }

    start = datetime.now()
    await bot_instance._acao_wait(page, acao, sessao)
    end = datetime.now()

    duracao = (end - start).total_seconds()

    # Deve ter aguardado aproximadamente 1 segundo
    assert 0.9 <= duracao <= 1.5

    await page.close()


# ========================================================================================
# TESTES DE MAPEAMENTO
# ========================================================================================


@pytest.mark.asyncio
async def test_mapear_pagina_atual(bot_instance):
    """Testa mapeamento de página"""
    contexto = await bot_instance._obter_contexto("TEST-MAP")
    page = await contexto.new_page()
    await page.goto("https://example.com")

    esquema = await bot_instance.mapear_pagina_atual(page)

    assert esquema is not None
    assert "url" in esquema
    assert "titulo" in esquema
    assert "total_elementos" in esquema
    assert "elementos" in esquema
    assert esquema["url"] == "https://example.com/"

    await page.close()


@pytest.mark.asyncio
async def test_mapear_pagina_com_filtros(bot_instance):
    """Testa mapeamento com filtros de tags"""
    contexto = await bot_instance._obter_contexto("TEST-MAP-FILTRO")
    page = await contexto.new_page()
    await page.goto("https://example.com")

    esquema = await bot_instance.mapear_pagina_atual(
        page, filtros=["a"]  # Apenas links
    )

    assert esquema is not None
    # Verificar que todos elementos são links
    for elem in esquema["elementos"]:
        assert elem["tag"] == "a"

    await page.close()


# ========================================================================================
# TESTES DE RETRY LOGIC
# ========================================================================================


@pytest.mark.asyncio
async def test_retry_logic_sucesso_primeira_tentativa(bot_instance):
    """Testa retry com sucesso na primeira tentativa"""
    contexto = await bot_instance._obter_contexto("TEST-RETRY")
    page = await contexto.new_page()
    await page.goto("https://example.com")

    sessao = SessionAuditoria(tenant_id="TEST-RETRY", session_id="test")

    acao = {
        "tipo": "screenshot",
        "path": "retry_test.png",
    }

    # Deve executar sem erros
    await bot_instance._executar_com_retry(
        bot_instance._acao_screenshot,
        page,
        acao,
        sessao,
    )

    # Verificar log
    assert len(sessao.logs) == 1
    assert sessao.logs[0]["status"] == "sucesso"
    assert sessao.logs[0]["detalhes"]["tentativa"] == 1

    await page.close()


# ========================================================================================
# TESTES DE GESTÃO DE ERROS
# ========================================================================================


@pytest.mark.asyncio
async def test_capturar_erro(bot_instance):
    """Testa captura de erro com screenshot e HTML"""
    contexto = await bot_instance._obter_contexto("TEST-ERRO")
    page = await contexto.new_page()
    await page.goto("https://example.com")

    screenshot_path = await bot_instance._capturar_erro(
        page,
        tenant_id="TEST-ERRO",
        session_id="test_session",
        contexto="test_action",
    )

    assert screenshot_path.exists()
    assert screenshot_path.suffix == ".png"

    # Verificar se HTML também foi salvo
    html_path = screenshot_path.with_suffix(".html")
    assert html_path.exists()

    await page.close()


def test_salvar_auditoria(bot_instance):
    """Testa salvamento de auditoria em JSON"""
    sessao = SessionAuditoria(
        tenant_id="TEST-AUDIT",
        session_id="test_session",
    )

    sessao.adicionar_log("goto", "sucesso")
    sessao.finalizar()

    filepath = bot_instance._salvar_auditoria(sessao)

    assert filepath.exists()
    assert filepath.suffix == ".json"

    # Verificar conteúdo
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["tenant_id"] == "TEST-AUDIT"
    assert data["session_id"] == "test_session"
    assert len(data["logs"]) == 1


# ========================================================================================
# TESTES DE INTEGRAÇÃO
# ========================================================================================


@pytest.mark.asyncio
async def test_fluxo_completo_multi_tenant(bot_instance):
    """Testa execução simultânea para múltiplos tenants"""
    config = {
        "nome": "Multi-tenant Test",
        "acoes": [
            {"tipo": "goto", "url": "https://example.com"},
            {"tipo": "screenshot", "path": "multi_tenant.png"},
        ],
    }

    tenants = ["TENANT-A", "TENANT-B", "TENANT-C"]

    tarefas = [bot_instance.executar_fluxo(config, tenant_id=tid) for tid in tenants]

    resultados = await asyncio.gather(*tarefas)

    assert len(resultados) == 3

    for idx, res in enumerate(resultados):
        sessao = res.sessao
        assert sessao.tenant_id == tenants[idx]
        assert sessao.status in ["concluido", "erro"]


# ========================================================================================
# TESTES DE VALIDAÇÃO
# ========================================================================================


def test_constantes_configuracao():
    """Testa valores das constantes de configuração"""
    assert AccountingBot.TIMEOUT_PADRAO == 30000
    assert AccountingBot.MAX_RETRIES == 3
    assert AccountingBot.RETRY_DELAY == 2000
    assert "red" in AccountingBot.HIGHLIGHT_STYLE.lower()


@pytest.mark.asyncio
async def test_diretorios_criados(bot_instance):
    """Testa se diretórios necessários são criados"""
    assert bot_instance._logs_dir.exists()
    assert bot_instance._screenshots_dir.exists()


# ========================================================================================
# TESTES DE EDGE CASES
# ========================================================================================


@pytest.mark.asyncio
async def test_acao_tipo_invalido(bot_instance):
    """Testa comportamento com tipo de ação inválido"""
    contexto = await bot_instance._obter_contexto("TEST-INVALID")
    page = await contexto.new_page()

    sessao = SessionAuditoria(tenant_id="TEST-INVALID", session_id="test")

    acao = {
        "tipo": "acao_inexistente",
    }

    with pytest.raises(ValueError, match="não suportado"):
        await bot_instance._executar_acao(page, acao, sessao)

    await page.close()


@pytest.mark.asyncio
async def test_config_sem_acoes(bot_instance):
    """Testa execução com configuração sem ações"""
    config = {
        "nome": "Config Vazia",
        "acoes": [],
    }

    resultado = await bot_instance.executar_fluxo(
        config=config,
        tenant_id="TEST-EMPTY",
    )

    sessao = resultado.sessao

    assert sessao.total_acoes == 0
    assert sessao.status == "concluido"


# ========================================================================================
# MARCADORES DE TESTE
# ========================================================================================


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fluxo_completo_com_delays():
    """Teste de integração completo (lento)"""
    bot = AccountingBot(headless=True)

    try:
        await bot.inicializar()

        config = {
            "nome": "Teste Completo",
            "acoes": [
                {"tipo": "goto", "url": "https://example.com"},
                {"tipo": "wait", "tempo": 2000},
                {"tipo": "screenshot", "path": "teste_completo.png"},
            ],
        }

        resultado = await bot.executar_fluxo(config, tenant_id="SLOW-TEST")
        sessao = resultado.sessao

        assert sessao.status == "concluido"
        assert sessao.total_acoes == 3

    finally:
        await bot.finalizar()


if __name__ == "__main__":
    # Executar testes com pytest
    pytest.main([__file__, "-v", "--tb=short"])
