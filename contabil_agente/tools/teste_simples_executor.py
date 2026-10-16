"""
Teste Simplificado do Motor de Execução Robótica
========================================================================================
Este script executa um teste básico sem necessidade de Playwright instalado.
Serve para validar a estrutura de classes e lógica de negócio.

Execução:
    python tools/teste_simples_executor.py
========================================================================================
"""

import sys
from pathlib import Path
from datetime import datetime

# Adicionar caminho ao sys.path
BASE_DIR = Path(__file__).parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def print_header(texto: str) -> None:
    """Imprime cabeçalho formatado"""
    print("\n" + "=" * 80)
    print(f"  {texto}")
    print("=" * 80)


def teste_1_importacoes():
    """Teste 1: Importações de classes"""
    print_header("TESTE 1: Importações de Classes")

    try:
        from tools.executor_motor import SessionAuditoria as SA
        from tools.executor_motor import ElementoMapeado as EM

        _ = SA
        _ = EM

        print("✅ SessionAuditoria importado")
        print("✅ ElementoMapeado importado")
        return True, "Todas as classes importadas com sucesso"
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False, str(e)


def teste_2_sessao_auditoria():
    """Teste 2: Criação e uso de SessionAuditoria"""
    print_header("TESTE 2: SessionAuditoria")

    try:
        from tools.executor_motor import SessionAuditoria

        # Criar sessão
        sessao = SessionAuditoria(tenant_id="TESTE-001", session_id="test_session_001")
        print(f"✅ Sessão criada: {sessao.tenant_id}")

        # Adicionar logs
        sessao.adicionar_log("goto", "sucesso", {"url": "https://example.com"})
        sessao.adicionar_log("click", "sucesso", {"selector": "#btn-login"})
        sessao.adicionar_log("fill", "erro", {"selector": "#senha", "erro": "Timeout"})
        print(f"✅ Logs adicionados: {sessao.total_acoes}")

        # Finalizar
        sessao.finalizar(status="concluido")
        print(f"✅ Sessão finalizada: {sessao.status}")

        # Converter para dict
        dict_sessao = sessao.para_dict()
        print(f"✅ Conversão para dict: {len(dict_sessao)} campos")

        # Validar dados
        assert dict_sessao["tenant_id"] == "TESTE-001"
        assert dict_sessao["total_acoes"] == 3
        assert dict_sessao["acoes_sucesso"] == 2
        assert dict_sessao["acoes_falha"] == 1
        assert dict_sessao["taxa_sucesso"] == 66.67

        print("\n📊 Resumo da Sessão:")
        print(f"   Tenant: {dict_sessao['tenant_id']}")
        print(f"   Total de ações: {dict_sessao['total_acoes']}")
        print(f"   Sucessos: {dict_sessao['acoes_sucesso']}")
        print(f"   Falhas: {dict_sessao['acoes_falha']}")
        print(f"   Taxa de sucesso: {dict_sessao['taxa_sucesso']}%")

        return True, "SessionAuditoria funcionando corretamente"

    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback

        traceback.print_exc()
        return False, str(e)


def teste_3_elemento_mapeado():
    """Teste 3: Criação e uso de ElementoMapeado"""
    print_header("TESTE 3: ElementoMapeado")

    try:
        from tools.executor_motor import ElementoMapeado

        # Criar elemento
        elemento = ElementoMapeado(
            tag_name="input",
            element_id="email",
            name="email",
            role="textbox",
            placeholder="Digite seu e-mail",
            text="",
            selector_css="#email",
            is_visible=True,
            is_enabled=True,
        )
        print(f"✅ Elemento criado: {elemento.tag_name}#{elemento.element_id}")

        # Converter para dict
        dict_elemento = elemento.para_dict()
        print(f"✅ Conversão para dict: {len(dict_elemento)} campos")

        # Validar dados
        assert dict_elemento["tag"] == "input"
        assert dict_elemento["id"] == "email"
        assert dict_elemento["seletores"]["css"] == "#email"
        assert dict_elemento["estado"]["visivel"] is True

        print("\n📋 Detalhes do Elemento:")
        print(f"   Tag: {dict_elemento['tag']}")
        print(f"   ID: {dict_elemento['id']}")
        print(f"   Seletor CSS: {dict_elemento['seletores']['css']}")
        print(f"   Visível: {dict_elemento['estado']['visivel']}")
        print(f"   Habilitado: {dict_elemento['estado']['habilitado']}")

        return True, "ElementoMapeado funcionando corretamente"

    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback

        traceback.print_exc()
        return False, str(e)


def teste_4_constantes():
    """Teste 4: Validação de constantes da classe AccountingBot"""
    print_header("TESTE 4: Constantes da Classe")

    try:
        from tools.executor_motor import AccountingBot

        # Validar constantes
        assert AccountingBot.TIMEOUT_PADRAO == 30000, "TIMEOUT_PADRAO incorreto"
        print(f"✅ TIMEOUT_PADRAO: {AccountingBot.TIMEOUT_PADRAO}ms")

        assert AccountingBot.MAX_RETRIES == 3, "MAX_RETRIES incorreto"
        print(f"✅ MAX_RETRIES: {AccountingBot.MAX_RETRIES}")

        assert AccountingBot.RETRY_DELAY == 2000, "RETRY_DELAY incorreto"
        print(f"✅ RETRY_DELAY: {AccountingBot.RETRY_DELAY}ms")

        assert "red" in AccountingBot.HIGHLIGHT_STYLE.lower(), "HIGHLIGHT_STYLE sem red"
        print(f"✅ HIGHLIGHT_STYLE: {AccountingBot.HIGHLIGHT_STYLE[:50]}...")

        return True, "Constantes validadas"

    except Exception as e:
        print(f"❌ Erro: {e}")
        return False, str(e)


def teste_5_estrutura_arquivos():
    """Teste 5: Verificar arquivos criados"""
    print_header("TESTE 5: Estrutura de Arquivos")

    arquivos_esperados = [
        "executor_motor.py",
        "demo_executor_motor.py",
        "test_executor_motor.py",
        "validar_executor_motor.py",
        "config_exemplo_login.json",
        "config_exemplo_nfe.json",
        "requirements_executor.txt",
        "README_EXECUTOR_MOTOR.md",
        "INSTALACAO_RAPIDA.md",
        "ENTREGA_COMPLETA.md",
        "COMPATIBILIDADE_PYTHON.md",
        "RESUMO_EXECUTIVO.md",
        "README.md",
    ]

    tools_dir = BASE_DIR / "tools"
    encontrados = 0
    faltantes = []

    for arquivo in arquivos_esperados:
        filepath = tools_dir / arquivo
        if filepath.exists():
            tamanho = filepath.stat().st_size
            print(f"✅ {arquivo:<35} ({tamanho:>8,} bytes)")
            encontrados += 1
        else:
            print(f"❌ {arquivo:<35} FALTANDO")
            faltantes.append(arquivo)

    print(f"\n📊 Total: {encontrados}/{len(arquivos_esperados)} arquivos encontrados")

    return len(faltantes) == 0, f"{encontrados}/{len(arquivos_esperados)} arquivos"


def main():
    """Função principal"""
    print("=" * 80)
    print("  🧪 TESTE SIMPLIFICADO DO MOTOR DE EXECUÇÃO ROBÓTICA")
    print("=" * 80)
    print(f"\n📂 Diretório base: {BASE_DIR}")
    print(f"🐍 Python: {sys.version.split()[0]}")
    print(f"📅 Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    resultados = {}

    # Executar testes
    testes = [
        ("Importações", teste_1_importacoes),
        ("SessionAuditoria", teste_2_sessao_auditoria),
        ("ElementoMapeado", teste_3_elemento_mapeado),
        ("Constantes", teste_4_constantes),
        ("Estrutura de Arquivos", teste_5_estrutura_arquivos),
    ]

    for nome, teste_func in testes:
        try:
            sucesso, detalhes = teste_func()
            resultados[nome] = {"sucesso": sucesso, "detalhes": detalhes}
        except Exception as e:
            resultados[nome] = {"sucesso": False, "detalhes": f"Erro: {e}"}

    # Relatório final
    print_header("RELATÓRIO FINAL")

    total = len(resultados)
    sucessos = sum(1 for r in resultados.values() if r["sucesso"])

    print(f"\n📊 Total de testes: {total}")
    print(f"✅ Sucessos: {sucessos}")
    print(f"❌ Falhas: {total - sucessos}")

    taxa_sucesso = (sucessos / total) * 100
    print(f"📈 Taxa de sucesso: {taxa_sucesso:.1f}%")

    if taxa_sucesso == 100:
        print("\n🎉 PARABÉNS! Todas as classes e estruturas estão funcionais!")
        print("✅ O Motor de Execução Robótica está pronto para uso!")
        print("\n📖 Próximos passos:")
        print("   1. Instalar Playwright: pip install playwright")
        print("   2. Instalar browsers: playwright install chromium")
        print("   3. Executar demo: python tools/demo_executor_motor.py")
        print("   4. Executar testes: pytest tools/test_executor_motor.py -v")
    else:
        print("\n⚠️  ATENÇÃO! Alguns testes falharam:")
        for nome, resultado in resultados.items():
            if not resultado["sucesso"]:
                print(f"\n❌ {nome}:")
                print(f"   Detalhes: {resultado['detalhes']}")

    # Código de saída
    sys.exit(0 if taxa_sucesso == 100 else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erro inesperado: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
