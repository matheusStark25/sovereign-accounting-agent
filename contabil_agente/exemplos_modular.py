"""
Exemplos de uso da estrutura modular
Demonstra como usar cada ferramenta isoladamente
"""

from decimal import Decimal


# ============================================
# EXEMPLO 1: Cálculo INSS/IRRF simples
# ============================================
def exemplo_calculo_tributos():
    """Demonstra uso do ToolCalculo"""
    from contabil_agente.tools.calculo_tool import ToolCalculo

    print("=" * 60)
    print("EXEMPLO 1: Cálculo de Tributos (INSS/IRRF 2026)")
    print("=" * 60)

    # Inicializa ferramenta
    calc = ToolCalculo()

    # Calcula INSS
    salario = Decimal("4500.00")
    inss = calc.calcular_inss(salario)
    print(f"\nSalário: R$ {salario:,.2f}")
    print(f"INSS:    R$ {inss:,.2f}")

    # Calcula IRRF
    base_irrf = salario - inss
    irrf = calc.calcular_irrf(base_irrf)
    print(f"IRRF:    R$ {irrf:,.2f}")

    liquido = salario - inss - irrf
    print(f"Líquido: R$ {liquido:,.2f}")
    print("\n✅ Cálculo usando tabelas oficiais 2026\n")


# ============================================
# EXEMPLO 2: Rescisão completa
# ============================================
def exemplo_rescisao_completa():
    """Demonstra cálculo completo de rescisão"""
    from contabil_agente.tools.calculo_tool import (
        DadosFuncionario,
        DadosRescisaoCalculo,
        ToolCalculo,
    )

    print("=" * 60)
    print("EXEMPLO 2: Rescisão Trabalhista Completa")
    print("=" * 60)

    # Dados do funcionário
    funcionario = DadosFuncionario(
        nome="Maria Santos",
        cpf="123.456.789-00",
        cargo="Analista",
        salario_base=Decimal("5000.00"),
        data_admissao="01/01/2023",
        data_demissao="28/01/2026",
        dependentes_irrf=1,
    )

    # Dados da rescisão
    rescisao = DadosRescisaoCalculo(
        tipo="sem_justa_causa",
        meses_trabalhados_total=36,
        meses_trabalhados_ano=1,
        dias_trabalhados_mes=28,
        ferias_vencidas=0,
        saldo_fgts_atual=Decimal("14400.00"),  # 5000 * 0.08 * 36
    )

    # Calcula
    calc = ToolCalculo()
    calc.aplicar_regras_por_tipo_rescisao(rescisao.tipo, rescisao)
    resultado = calc.calcular_rescisao_completa(funcionario, rescisao)

    if resultado["status"] == "success":
        detalhes = resultado["detalhes"]

        print(f"\nFuncionário: {funcionario.nome}")
        print(f"Tipo: {rescisao.tipo.replace('_', ' ').title()}")
        print(f"\n{'VERBAS RESCISÓRIAS':^60}")
        print("-" * 60)
        print(f"Saldo salário:           R$ {detalhes['saldo_salario']:>10,.2f}")
        print(f"Aviso prévio:            R$ {detalhes['aviso_previo']:>10,.2f}")
        print(f"Férias proporcionais:    R$ {detalhes['ferias_proporcionais']:>10,.2f}")
        print(f"13º proporcional:        R$ {detalhes['decimo_terceiro']:>10,.2f}")
        print(f"Multa FGTS (40%):        R$ {detalhes['multa_fgts']:>10,.2f}")
        print("-" * 60)
        print(f"Total proventos:         R$ {detalhes['total_proventos']:>10,.2f}")
        print(f"Total descontos:         R$ {detalhes['total_descontos']:>10,.2f}")
        print(f"\n{'VALOR LÍQUIDO':^60}")
        print(f"{'R$ ' + f'{detalhes['total_liquido']:,.2f}':^60}")
        print("\n✅ Rescisão calculada conforme CLT\n")

        # Mostra explanation
        print("📊 Detalhamento do cálculo:")
        for linha in resultado["explanation"][:5]:
            print(f"  • {linha}")
        print()
    else:
        print(f"❌ Erro: {resultado['message']}\n")


# ============================================
# EXEMPLO 3: Auditoria em tempo real
# ============================================
def exemplo_auditoria():
    """Demonstra sistema de auditoria"""
    from contabil_agente.utils.audit import send_audit

    print("=" * 60)
    print("EXEMPLO 3: Sistema de Auditoria")
    print("=" * 60)

    # Registra eventos
    send_audit(
        "Operação de teste iniciada",
        level="info",
        context={"usuario": "teste", "modulo": "exemplo"},
    )

    send_audit(
        "Cálculo processado", level="info", context={"valor": 5000, "resultado": 4200}
    )

    send_audit(
        "PDF gerado com sucesso", level="info", context={"documento": "TRCT-123456.pdf"}
    )

    print("\n✅ Eventos registrados em logs/evolucao_sistema.json")
    print("ℹ️  Use o dashboard de auditoria para visualizar\n")


# ============================================
# EXEMPLO 4: Database Pool
# ============================================
def exemplo_database():
    """Demonstra uso do pool de conexões"""
    from contabil_agente.core.database import DatabasePool, TableCache

    print("=" * 60)
    print("EXEMPLO 4: Pool de Conexões SQLite")
    print("=" * 60)

    # Pool singleton
    pool = DatabasePool()
    print(f"\n✅ Pool inicializado com {pool.pool_size} conexões")

    # Usa conexão
    conn = pool.get_connection()
    print("✅ Conexão obtida do pool")

    # Executa query
    cursor = conn.cursor()
    cursor.execute("SELECT 1 as teste")
    result = cursor.fetchone()
    print(f"✅ Query executada: {dict(result)}")

    # Retorna ao pool
    pool.return_connection(conn)
    print("✅ Conexão devolvida ao pool\n")

    # Cache
    cache = TableCache(pool)
    cache.set("teste", {"valor": 123}, ttl=3600)
    valor = cache.get("teste")
    print(f"✅ Cache funcionando: {valor}\n")


# ============================================
# EXEMPLO 5: Helpers e conversões
# ============================================
def exemplo_helpers():
    """Demonstra funções auxiliares"""
    from contabil_agente.utils.helpers import _ensure_resposta_str

    print("=" * 60)
    print("EXEMPLO 5: Funções Auxiliares")
    print("=" * 60)

    # Testa conversão segura
    obj = {"mensagem": "Olá! 😊", "valor": 1234.56}
    resultado = _ensure_resposta_str(obj)
    print(f"\nObjeto original: {obj}")
    print(f"String segura: {resultado}")
    print("✅ Conversão UTF-8 segura aplicada\n")


# ============================================
# RUNNER PRINCIPAL
# ============================================
def main():
    """Executa todos os exemplos"""

    print("\n")
    print("*" * 60)
    print("*" + " " * 58 + "*")
    print("*" + "EXEMPLOS DE USO - ESTRUTURA MODULAR OOP".center(58) + "*")
    print("*" + " " * 58 + "*")
    print("*" * 60)
    print("\n")

    exemplos = [
        exemplo_calculo_tributos,
        exemplo_rescisao_completa,
        exemplo_auditoria,
        exemplo_database,
        exemplo_helpers,
    ]

    for i, exemplo in enumerate(exemplos, 1):
        try:
            exemplo()
        except Exception as e:
            print(f"\n❌ Erro no exemplo {i}: {e}\n")
            import traceback

            traceback.print_exc()

        if i < len(exemplos):
            input("Pressione ENTER para continuar...")
            print("\n")

    print("*" * 60)
    print("*" + "EXEMPLOS CONCLUÍDOS!".center(58) + "*")
    print("*" * 60)
    print("\n📚 Veja MODULAR_README.md para mais informações\n")


if __name__ == "__main__":
    main()
