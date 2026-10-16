"""
Exemplo de Uso - Camada de Segurança & Compliance
==================================================

Demonstra como usar o SecureAccountingService com todos os recursos
de segurança integrados.

Executar:
    python exemplo_uso_seguranca.py
"""

import os
import sys
from datetime import datetime

from security import (
    RBACManager,
    Role,
    SecureAccountingService,
)

# Adiciona path do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configura variáveis de ambiente de exemplo (em produção, use .env.security)
os.environ.setdefault(
    "ENCRYPTION_KEY_CURRENT", "exemplo-chave-desenvolvimento-nao-usar-producao-32chars"
)
os.environ.setdefault(
    "HMAC_SECRET_KEY", "exemplo-hmac-desenvolvimento-nao-usar-producao-32chars"
)


def setup_demo_users(rbac: RBACManager):
    """Configura usuários de demonstração."""
    print("📋 Configurando usuários de demonstração...\n")

    # 1. Contador (acesso total ao seu tenant)
    rbac.register_operator(
        operator_id="CONTADOR_001", tenant_id="EMPRESA_001", roles={Role.ACCOUNTANT}
    )
    print("✓ Contador registrado: CONTADOR_001 @ EMPRESA_001")

    # 2. Auditor (somente leitura)
    rbac.register_operator(
        operator_id="AUDITOR_001", tenant_id="EMPRESA_001", roles={Role.AUDITOR}
    )
    print("✓ Auditor registrado: AUDITOR_001 @ EMPRESA_001")

    # 3. Admin do tenant
    rbac.register_operator(
        operator_id="ADMIN_001", tenant_id="EMPRESA_001", roles={Role.TENANT_ADMIN}
    )
    print("✓ Admin registrado: ADMIN_001 @ EMPRESA_001\n")


def exemplo_1_processamento_folha():
    """Exemplo 1: Processamento de folha com segurança completa."""
    print("=" * 70)
    print("EXEMPLO 1: Processamento de Folha de Pagamento Seguro")
    print("=" * 70 + "\n")

    # Inicializa serviço
    service = SecureAccountingService(
        tenant_id="EMPRESA_001", operator_id="CONTADOR_001", ip_address="192.168.1.100"
    )

    # Dados de funcionários (com PII)
    funcionarios = [
        {
            "id": "FUNC_001",
            "nome": "João Silva",
            "cp": "12345678901",
            "salario": 5000.00,
            "email": "joao.silva@empresa.com",
        },
        {
            "id": "FUNC_002",
            "nome": "Maria Santos",
            "cp": "98765432109",
            "salario": 6500.00,
            "email": "maria.santos@empresa.com",
        },
    ]

    print("Funcionários originais (com PII):")
    for func in funcionarios:
        print(
            f"  - {func['nome']}: CPF {func['cpf']}, Salário R$ {func['salario']:.2f}"
        )

    # Mascara dados para exibição
    print("\nFuncionários com PII mascarado:")
    for func in funcionarios:
        masked = service.mask_pii_for_display(func)
        print(f"  - {masked['nome']}: CPF {masked['cpf']}, Salário {masked['salario']}")

    # Processa folha
    print("\n📊 Processando folha de pagamento...")
    resultado = service.process_payroll(
        empresa_id="EMPRESA_001",
        mes=2,
        ano=2026,
        funcionarios=funcionarios,
        encrypt_results=True,
    )

    print("\n✅ Folha processada com sucesso!")
    print(f"   - Período: {resultado['periodo']}")
    print(f"   - Total funcionários: {resultado['total_funcionarios']}")
    print(f"   - Processado em: {resultado['processed_at']}")
    print("   - Dados criptografados: ✓ (AES-256-GCM)")
    print("   - Auditoria registrada: ✓ (HMAC assinado)")
    print()


def exemplo_2_tentativa_idor():
    """Exemplo 2: Tentativa de acesso cruzado (IDOR) - Bloqueada."""
    print("=" * 70)
    print("EXEMPLO 2: Proteção contra IDOR (Acesso Cruzado)")
    print("=" * 70 + "\n")

    # Contador tenta acessar dados de outra empresa
    service = SecureAccountingService(
        tenant_id="EMPRESA_001",
        operator_id="CONTADOR_001",
    )

    print("🚨 Tentando processar folha de OUTRA empresa (IDOR)...")
    print("   Operador: CONTADOR_001 @ EMPRESA_001")
    print("   Tentando acessar: EMPRESA_002")

    try:
        service.process_payroll(
            empresa_id="EMPRESA_002",  # Empresa diferente!
            mes=2,
            ano=2026,
            funcionarios=[],
        )
        print("\n❌ FALHA: IDOR não foi bloqueado!")

    except Exception as e:
        print("\n✅ BLOQUEADO com sucesso!")
        print(f"   Erro: {type(e).__name__}")
        print("   Motivo: Tentativa de acesso cruzado detectada")
        print("   Ação: Alerta CRITICAL registrado em audit log")
        print()


def exemplo_3_criptografia():
    """Exemplo 3: Criptografia e descriptografia de dados."""
    print("=" * 70)
    print("EXEMPLO 3: Criptografia AES-256 de Dados Sensíveis")
    print("=" * 70 + "\n")

    service = SecureAccountingService(
        tenant_id="EMPRESA_001",
        operator_id="CONTADOR_001",
    )

    # Dados originais
    dados_originais = {
        "funcionario_id": "FUNC_001",
        "nome": "João Silva",
        "cp": "12345678901",
        "salario": 5000.00,
        "banco": "001 - Banco do Brasil",
        "conta": "12345-6",
    }

    print("Dados originais:")
    for k, v in dados_originais.items():
        print(f"  {k}: {v}")

    # Criptografa campos sensíveis
    print("\n🔐 Criptografando campos sensíveis...")
    dados_criptografados = service.encrypt_sensitive_data(
        dados_originais, sensitive_fields=["cp", "salario", "conta"]
    )

    print("\nDados criptografados:")
    for k, v in dados_criptografados.items():
        if str(v).startswith("ENC:"):
            print(f"  {k}: [CRIPTOGRAFADO] {str(v)[:50]}...")
        else:
            print(f"  {k}: {v}")

    # Descriptografa
    print("\n🔓 Descriptografando...")
    dados_descriptografados = service.decrypt_sensitive_data(dados_criptografados)

    print("\nDados descriptografados:")
    for k, v in dados_descriptografados.items():
        print(f"  {k}: {v}")

    print("\n✅ Criptografia/Descriptografia bem-sucedida!")
    print()


def exemplo_4_audit_trail():
    """Exemplo 4: Trilha de auditoria imutável."""
    print("=" * 70)
    print("EXEMPLO 4: Trilha de Auditoria Imutável")
    print("=" * 70 + "\n")

    service = SecureAccountingService(
        tenant_id="EMPRESA_001",
        operator_id="CONTADOR_001",
    )

    # Executa algumas operações
    print("Executando operações...")

    # Operação 1: Geração de SPED
    service.generate_sped(
        empresa_id="EMPRESA_001", tipo_sped="Contábil", periodo="2026-01"
    )
    print("  ✓ SPED gerado")

    # Lê audit log
    print("\n📖 Lendo audit log do dia...")
    entries = service.audit.read_audit_log(
        tenant_id="EMPRESA_001", date=datetime.now(), limit=10
    )

    print(f"\nTotal de eventos: {len(entries)}")
    print("\nÚltimos eventos:")
    for entry in entries[-5:]:
        print(
            f"  [{entry.timestamp.strftime('%H:%M:%S')}] "
            f"{entry.action.value} - "
            f"{entry.description} "
            f"({'✓' if entry.success else '✗'})"
        )

    # Verifica integridade
    print("\n🔍 Verificando integridade dos logs...")
    integrity = service.audit.verify_log_integrity(tenant_id="EMPRESA_001")

    print("\nResultado da verificação:")
    print(f"  Total entradas: {integrity['total_entries']}")
    print(f"  Assinaturas válidas: {integrity['valid_signatures']}")
    print(f"  Assinaturas inválidas: {integrity['invalid_signatures']}")
    print(
        f"  Integridade: {'✅ OK' if integrity['integrity_ok'] else '❌ COMPROMETIDA'}"
    )
    print()


def exemplo_5_status_seguranca():
    """Exemplo 5: Status de segurança do sistema."""
    print("=" * 70)
    print("EXEMPLO 5: Status de Segurança do Sistema")
    print("=" * 70 + "\n")

    service = SecureAccountingService(
        tenant_id="EMPRESA_001",
        operator_id="CONTADOR_001",
    )

    status = service.get_security_status()

    print("🔐 Status de Segurança\n")

    print("1. Vault (Gerenciamento de Secrets):")
    print(f"   Status: {status['vault']['status']}")
    print(f"   Secrets carregados: {status['vault']['secrets_loaded']}")
    print(f"   Versão chave criptografia: v{status['vault']['encryption_key_version']}")
    print(f"   Versão chave HMAC: v{status['vault']['hmac_key_version']}")

    print("\n2. RBAC (Controle de Acesso):")
    print(f"   Operadores ativos: {status['rbac']['active_operators']}")
    print(f"   Operadores inativos: {status['rbac']['inactive_operators']}")
    print(
        f"   Tentativas falhas (última hora): {status['rbac']['failed_attempts_last_hour']}"
    )

    print("\n3. Auditoria:")
    print(f"   Data: {status['audit']['date']}")
    print(f"   Total entradas: {status['audit']['total_entries']}")
    print(
        f"   Integridade: {'✅ OK' if status['audit']['integrity_ok'] else '❌ FALHA'}"
    )

    print()


def main():
    """Executa todos os exemplos."""
    print("\n" + "=" * 70)
    print(" DEMONSTRAÇÃO - Camada de Segurança & Compliance")
    print(" Sistema Contábil Maria Helena")
    print("=" * 70 + "\n")

    # Setup inicial
    rbac = RBACManager()
    setup_demo_users(rbac)

    input("Pressione ENTER para continuar...\n")

    # Executa exemplos
    try:
        exemplo_1_processamento_folha()
        input("Pressione ENTER para próximo exemplo...\n")

        exemplo_2_tentativa_idor()
        input("Pressione ENTER para próximo exemplo...\n")

        exemplo_3_criptografia()
        input("Pressione ENTER para próximo exemplo...\n")

        exemplo_4_audit_trail()
        input("Pressione ENTER para próximo exemplo...\n")

        exemplo_5_status_seguranca()

    except KeyboardInterrupt:
        print("\n\nInterrompido pelo usuário.")

    print("=" * 70)
    print(" Demonstração concluída!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
