"""
Script de Validação Automática do Motor de Execução Robótica
========================================================================================
Este script verifica se todos os componentes estão corretamente instalados e funcionais.

Execução:
    python tools/validar_executor_motor.py
========================================================================================
"""

import sys
import subprocess
from pathlib import Path
from typing import List, Tuple
import json

# ========================================================================================
# CONFIGURAÇÕES
# ========================================================================================

BASE_DIR = Path(__file__).parent.parent
TOOLS_DIR = BASE_DIR / "tools"
LOGS_DIR = BASE_DIR / "logs" / "automacao"

ARQUIVOS_ESPERADOS = [
    "tools/executor_motor.py",
    "tools/demo_executor_motor.py",
    "tools/test_executor_motor.py",
    "tools/config_exemplo_login.json",
    "tools/config_exemplo_nfe.json",
    "tools/requirements_executor.txt",
    "tools/README_EXECUTOR_MOTOR.md",
    "tools/INSTALACAO_RAPIDA.md",
    "tools/ENTREGA_COMPLETA.md",
]

DEPENDENCIAS_NECESSARIAS = [
    "playwright",
    "pytest",
    "pytest-asyncio",
]


# ========================================================================================
# FUNÇÕES DE VALIDAÇÃO
# ========================================================================================


def print_header(texto: str) -> None:
    """Imprime cabeçalho formatado"""
    print("\n" + "=" * 80)
    print(f"  {texto}")
    print("=" * 80)


def print_status(item: str, sucesso: bool, detalhes: str = "") -> None:
    """Imprime status de validação"""
    simbolo = "✅" if sucesso else "❌"
    print(f"{simbolo} {item:<50} {detalhes}")


def validar_estrutura_arquivos() -> Tuple[bool, List[str]]:
    """Valida se todos os arquivos esperados existem"""
    print_header("VALIDAÇÃO 1: Estrutura de Arquivos")

    faltantes = []

    for arquivo_rel in ARQUIVOS_ESPERADOS:
        arquivo_path = BASE_DIR / arquivo_rel
        existe = arquivo_path.exists()

        if existe:
            tamanho = arquivo_path.stat().st_size
            detalhes = f"({tamanho:,} bytes)"
        else:
            detalhes = "FALTANDO"
            faltantes.append(arquivo_rel)

        print_status(arquivo_rel, existe, detalhes)

    return len(faltantes) == 0, faltantes


def validar_dependencias() -> Tuple[bool, List[str]]:
    """Valida se dependências estão instaladas"""
    print_header("VALIDAÇÃO 2: Dependências Python")

    faltantes = []

    for dep in DEPENDENCIAS_NECESSARIAS:
        try:
            __import__(dep.replace("-", "_"))
            print_status(dep, True, "instalado")
        except ImportError:
            print_status(dep, False, "NÃO instalado")
            faltantes.append(dep)

    return len(faltantes) == 0, faltantes


def validar_playwright_browsers() -> Tuple[bool, str]:
    """Valida se navegadores do Playwright estão instalados"""
    print_header("VALIDAÇÃO 3: Browsers do Playwright")

    try:
        # Run without capturing output so the installer logs stream to the terminal
        resultado = subprocess.run(
            ["playwright", "install", "--dry-run", "chromium"],
            check=False,
            timeout=10,
        )

        # Se não houver erros, consideramos instalado
        sucesso = (
            resultado.returncode == 0 or "already installed" in resultado.stdout.lower()
        )

        detalhes = "Chromium instalado" if sucesso else "Chromium NÃO instalado"
        print_status("playwright chromium", sucesso, detalhes)

        return sucesso, detalhes

    except FileNotFoundError:
        print_status("playwright CLI", False, "playwright não encontrado no PATH")
        return False, "Playwright CLI não encontrado"
    except Exception as e:
        print_status("playwright browsers", False, f"Erro: {e}")
        return False, str(e)


def validar_importacao_executor() -> Tuple[bool, str]:
    """Valida se o módulo executor_motor pode ser importado"""
    print_header("VALIDAÇÃO 4: Importação do Módulo")

    try:
        # Adicionar caminho ao sys.path
        if str(TOOLS_DIR.parent) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR.parent))

        __import__("tools.executor_motor")

        print_status("tools.executor_motor", True, "importado")

        return True, "Todos os componentes importados com sucesso"

    except Exception as e:
        print_status("executor_motor", False, f"Erro: {e}")
        return False, str(e)


def validar_diretorios() -> Tuple[bool, List[str]]:
    """Valida se diretórios necessários existem ou podem ser criados"""
    print_header("VALIDAÇÃO 5: Diretórios")

    diretorios = [
        LOGS_DIR,
        LOGS_DIR / "screenshots",
        LOGS_DIR / "downloads",
    ]

    problemas = []

    for diretorio in diretorios:
        try:
            diretorio.mkdir(parents=True, exist_ok=True)
            print_status(str(diretorio.relative_to(BASE_DIR)), True, "OK")
        except Exception as e:
            print_status(str(diretorio.relative_to(BASE_DIR)), False, f"Erro: {e}")
            problemas.append(str(diretorio))

    return len(problemas) == 0, problemas


def validar_configs_json() -> Tuple[bool, List[str]]:
    """Valida se arquivos JSON de configuração são válidos"""
    print_header("VALIDAÇÃO 6: Configurações JSON")

    configs = [
        "tools/config_exemplo_login.json",
        "tools/config_exemplo_nfe.json",
    ]

    invalidos = []

    for config_rel in configs:
        config_path = BASE_DIR / config_rel

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validar estrutura básica
            assert "nome" in data, "Campo 'nome' ausente"
            assert "acoes" in data, "Campo 'acoes' ausente"
            assert isinstance(data["acoes"], list), "'acoes' deve ser uma lista"

            num_acoes = len(data["acoes"])
            print_status(config_rel, True, f"{num_acoes} ações")

        except json.JSONDecodeError as e:
            print_status(config_rel, False, f"JSON inválido: {e}")
            invalidos.append(config_rel)
        except AssertionError as e:
            print_status(config_rel, False, f"Estrutura inválida: {e}")
            invalidos.append(config_rel)
        except Exception as e:
            print_status(config_rel, False, f"Erro: {e}")
            invalidos.append(config_rel)

    return len(invalidos) == 0, invalidos


def executar_teste_basico() -> Tuple[bool, str]:
    """Executa um teste básico de criação de objetos"""
    print_header("VALIDAÇÃO 7: Teste Básico de Funcionalidade")

    try:
        if str(TOOLS_DIR.parent) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR.parent))

        from tools.executor_motor import SessionAuditoria, ElementoMapeado

        # Teste 1: SessionAuditoria
        sessao = SessionAuditoria(tenant_id="TEST", session_id="test_001")
        sessao.adicionar_log("teste", "sucesso")
        sessao.finalizar()

        assert sessao.total_acoes == 1, "Total de ações incorreto"
        assert sessao.acoes_sucesso == 1, "Ações de sucesso incorretas"
        assert sessao.status == "concluido", "Status incorreto"

        print_status("SessionAuditoria.adicionar_log()", True, "OK")
        print_status("SessionAuditoria.finalizar()", True, "OK")

        # Teste 2: ElementoMapeado
        elemento = ElementoMapeado(
            tag_name="input",
            element_id="teste",
            is_visible=True,
        )

        dict_elem = elemento.para_dict()
        assert dict_elem["tag"] == "input", "Tag incorreta"

        print_status("ElementoMapeado.para_dict()", True, "OK")

        return True, "Todos os testes básicos passaram"

    except Exception as e:
        print_status("Teste básico", False, f"Erro: {e}")
        return False, str(e)


def gerar_relatorio_final(resultados: dict) -> None:
    """Gera relatório final da validação"""
    print_header("RELATÓRIO FINAL")

    total_validacoes = len(resultados)
    validacoes_sucesso = sum(1 for r in resultados.values() if r["sucesso"])

    print(f"\n📊 Total de validações: {total_validacoes}")
    print(f"✅ Sucessos: {validacoes_sucesso}")
    print(f"❌ Falhas: {total_validacoes - validacoes_sucesso}")

    taxa_sucesso = (validacoes_sucesso / total_validacoes) * 100
    print(f"📈 Taxa de sucesso: {taxa_sucesso:.1f}%")

    if taxa_sucesso == 100:
        print("\n🎉 PARABÉNS! Todos os componentes estão instalados e funcionais!")
        print("✅ O Motor de Execução Robótica está pronto para uso!")
        print("\n📖 Próximos passos:")
        print("   1. Execute: python tools/demo_executor_motor.py")
        print("   2. Execute: pytest tools/test_executor_motor.py -v")
        print("   3. Leia: tools/README_EXECUTOR_MOTOR.md")
    else:
        print("\n⚠️  ATENÇÃO! Alguns componentes precisam de atenção:")

        for nome, resultado in resultados.items():
            if not resultado["sucesso"]:
                print(f"\n❌ {nome}:")
                print(f"   Detalhes: {resultado['detalhes']}")

                # Sugestões de correção
                if "Dependências" in nome:
                    print("   Solução: pip install -r tools/requirements_executor.txt")
                elif "Browsers" in nome:
                    print("   Solução: playwright install chromium")
                elif "Importação" in nome:
                    print(
                        "   Solução: Verifique se todas as dependências estão instaladas"
                    )


# ========================================================================================
# EXECUÇÃO PRINCIPAL
# ========================================================================================


def main():
    """Função principal de validação"""
    print("=" * 80)
    print("  🔍 VALIDAÇÃO AUTOMÁTICA DO MOTOR DE EXECUÇÃO ROBÓTICA")
    print("=" * 80)
    print(f"\n📂 Diretório base: {BASE_DIR}")
    print(f"🐍 Python: {sys.version.split()[0]}")

    resultados = {}

    # Validação 1: Estrutura de arquivos
    sucesso, detalhes = validar_estrutura_arquivos()
    resultados["Estrutura de Arquivos"] = {
        "sucesso": sucesso,
        "detalhes": f"{len(ARQUIVOS_ESPERADOS) - len(detalhes)}/{len(ARQUIVOS_ESPERADOS)} arquivos encontrados",
    }

    # Validação 2: Dependências
    sucesso, detalhes = validar_dependencias()
    resultados["Dependências Python"] = {
        "sucesso": sucesso,
        "detalhes": f"{len(DEPENDENCIAS_NECESSARIAS) - len(detalhes)}/{len(DEPENDENCIAS_NECESSARIAS)} instaladas",
    }

    # Validação 3: Browsers
    sucesso, detalhes = validar_playwright_browsers()
    resultados["Browsers do Playwright"] = {"sucesso": sucesso, "detalhes": detalhes}

    # Validação 4: Importação
    sucesso, detalhes = validar_importacao_executor()
    resultados["Importação do Módulo"] = {"sucesso": sucesso, "detalhes": detalhes}

    # Validação 5: Diretórios
    sucesso, detalhes = validar_diretorios()
    resultados["Diretórios"] = {
        "sucesso": sucesso,
        "detalhes": (
            "Todos os diretórios OK" if sucesso else f"{len(detalhes)} problemas"
        ),
    }

    # Validação 6: Configs JSON
    sucesso, detalhes = validar_configs_json()
    resultados["Configurações JSON"] = {
        "sucesso": sucesso,
        "detalhes": (
            "Todos os JSONs válidos" if sucesso else f"{len(detalhes)} inválidos"
        ),
    }

    # Validação 7: Teste básico
    sucesso, detalhes = executar_teste_basico()
    resultados["Teste Básico"] = {"sucesso": sucesso, "detalhes": detalhes}

    # Relatório final
    gerar_relatorio_final(resultados)

    # Retornar código de saída
    todos_sucesso = all(r["sucesso"] for r in resultados.values())
    sys.exit(0 if todos_sucesso else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Validação interrompida pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erro inesperado durante validação: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
