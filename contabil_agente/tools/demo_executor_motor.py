"""
Script de Demonstração do Motor de Automação Contábil
========================================================================================
Exemplos práticos de uso do executor_motor.py

Execução:
    python tools/demo_executor_motor.py
========================================================================================
"""

import asyncio
import json
from pathlib import Path
from executor_motor import AccountingBot, executar_automacao_contabil


async def exemplo_1_basico():
    """Exemplo 1: Uso básico com configuração inline"""
    print("\n" + "=" * 80)
    print("📘 EXEMPLO 1: Uso Básico com Configuração Inline")
    print("=" * 80)

    # Configuração simples
    config = {
        "nome": "Teste Básico",
        "acoes": [
            {
                "tipo": "goto",
                "url": "https://example.com",
            },
            {
                "tipo": "screenshot",
                "path": "exemplo_basico.png",
            },
        ],
    }

    # Criar e executar bot
    bot = AccountingBot(headless=False)  # headless=False para ver o navegador

    try:
        await bot.inicializar()

        resultado = await bot.executar_fluxo(
            config=config,
            tenant_id="DEMO-001",
        )

        sessao = resultado.sessao

        print(f"\n✅ Status: {sessao.status}")
        print(f"📊 Total de ações: {sessao.total_acoes}")
        print(f"✅ Sucessos: {sessao.acoes_sucesso}")
        print(f"❌ Falhas: {sessao.acoes_falha}")

    finally:
        await bot.finalizar()


async def exemplo_2_com_arquivo_json():
    """Exemplo 2: Carregando configuração de arquivo JSON"""
    print("\n" + "=" * 80)
    print("📘 EXEMPLO 2: Carregando Configuração de Arquivo JSON")
    print("=" * 80)

    # Verificar se arquivo existe
    config_path = Path("tools/config_exemplo_login.json")

    if not config_path.exists():
        print(f"❌ Arquivo não encontrado: {config_path}")
        print("⚠️  Execute este script do diretório raiz do projeto")
        return

    # Usar função helper
    sessao = await executar_automacao_contabil(
        config_path=str(config_path),
        tenant_id="EMPRESA-001",
        headless=False,
    )

    print(f"\n✅ Status: {sessao.status}")
    print(f"📊 Total de ações: {sessao.total_acoes}")
    print(f"📸 Screenshots capturados: {len(sessao.screenshots)}")


async def exemplo_3_mapeamento_pagina():
    """Exemplo 3: Mapeamento inteligente de página"""
    print("\n" + "=" * 80)
    print("📘 EXEMPLO 3: Mapeamento Inteligente de Página")
    print("=" * 80)

    bot = AccountingBot(headless=False)

    try:
        await bot.inicializar()

        # Obter contexto e criar página
        contexto = await bot._obter_contexto("MAPEAMENTO-DEMO")
        page = await contexto.new_page()

        # Navegar para página de exemplo
        await page.goto("https://www.google.com")
        await asyncio.sleep(2)  # Aguardar carregamento

        # Mapear página
        esquema = await bot.mapear_pagina_atual(page)

        # Salvar esquema
        output_path = Path("logs/automacao/mapeamento_google.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(esquema, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Página mapeada: {esquema['url']}")
        print(f"📊 Elementos encontrados: {esquema['total_elementos']}")
        print(f"💾 Esquema salvo em: {output_path}")

        # Mostrar exemplos de elementos
        print("\n📋 Exemplos de elementos mapeados:")
        for elem in esquema["elementos"][:5]:  # Primeiros 5 elementos
            print(f"   - {elem['tag']}: {elem.get('seletores', {}).get('css', 'N/A')}")

        await page.close()

    finally:
        await bot.finalizar()


async def exemplo_4_multi_tenancy():
    """Exemplo 4: Múltiplos tenants simultâneos"""
    print("\n" + "=" * 80)
    print("📘 EXEMPLO 4: Multi-tenancy (Múltiplos Tenants Simultâneos)")
    print("=" * 80)

    bot = AccountingBot(headless=False)

    try:
        await bot.inicializar()

        # Configuração base
        config_base = {
            "nome": "Teste Multi-Tenant",
            "acoes": [
                {
                    "tipo": "goto",
                    "url": "https://example.com",
                },
                {
                    "tipo": "screenshot",
                    "path": "tenant_{}.png",
                },
            ],
        }

        # Executar para 3 tenants simultaneamente
        tenants = ["EMPRESA-A", "EMPRESA-B", "EMPRESA-C"]

        tarefas = []
        for tenant_id in tenants:
            # Customizar config para cada tenant
            config = config_base.copy()
            config["acoes"][1]["path"] = f"tenant_{tenant_id}.png"

            # Criar tarefa assíncrona
            tarefa = bot.executar_fluxo(
                config=config,
                tenant_id=tenant_id,
                session_id=f"session_{tenant_id}",
            )
            tarefas.append(tarefa)

        # Executar todas em paralelo
        resultados = await asyncio.gather(*tarefas)

        # Mostrar resultados
        print("\n📊 Resultados por Tenant:")
        for res in resultados:
            sessao = res.sessao
            print(
                f"   - {sessao.tenant_id}: {sessao.status} ({sessao.acoes_sucesso}/{sessao.total_acoes} sucessos)"
            )

    finally:
        await bot.finalizar()


async def exemplo_5_retry_logic():
    """Exemplo 5: Demonstração do Retry Logic"""
    print("\n" + "=" * 80)
    print("📘 EXEMPLO 5: Retry Logic em Ação")
    print("=" * 80)

    # Configuração com seletor que pode falhar
    config = {
        "nome": "Teste de Retry",
        "acoes": [
            {
                "tipo": "goto",
                "url": "https://example.com",
            },
            {
                "tipo": "click",
                "selector": "#elemento-que-pode-nao-existir",
                "timeout": 3000,  # Timeout curto para forçar retry
                "critico": False,  # Não crítico - continuar em caso de falha
            },
            {
                "tipo": "screenshot",
                "path": "apos_tentativa.png",
            },
        ],
    }

    bot = AccountingBot(headless=False)

    try:
        await bot.inicializar()

        resultado = await bot.executar_fluxo(
            config=config,
            tenant_id="RETRY-DEMO",
        )

        sessao = resultado.sessao

        print(f"\n✅ Execução finalizada: {sessao.status}")
        print("\n📋 Logs detalhados:")
        for log in sessao.logs:
            print(f"   [{log['timestamp']}] {log['acao']}: {log['status']}")

    finally:
        await bot.finalizar()


async def menu_principal():
    """Menu interativo para escolher exemplo"""
    print("\n" + "=" * 80)
    print("🤖 DEMONSTRAÇÃO DO MOTOR DE AUTOMAÇÃO CONTÁBIL")
    print("=" * 80)
    print("\nEscolha um exemplo para executar:")
    print("\n1. Uso Básico (configuração inline)")
    print("2. Carregar de Arquivo JSON")
    print("3. Mapeamento Inteligente de Página")
    print("4. Multi-tenancy (Múltiplos Tenants)")
    print("5. Retry Logic em Ação")
    print("6. Executar TODOS os exemplos")
    print("0. Sair")

    escolha = input("\nDigite o número da opção: ").strip()

    exemplos = {
        "1": exemplo_1_basico,
        "2": exemplo_2_com_arquivo_json,
        "3": exemplo_3_mapeamento_pagina,
        "4": exemplo_4_multi_tenancy,
        "5": exemplo_5_retry_logic,
    }

    if escolha == "0":
        print("\n👋 Até logo!")
        return

    if escolha == "6":
        # Executar todos
        for nome, exemplo in exemplos.items():
            await exemplo()
            print("\n⏸️  Pressione ENTER para continuar...")
            input()
    elif escolha in exemplos:
        await exemplos[escolha]()
    else:
        print("\n❌ Opção inválida!")


if __name__ == "__main__":
    # Executar menu interativo
    asyncio.run(menu_principal())
