"""
Testes Unitários - Camada de Segurança & Compliance
====================================================

Testa todos os componentes de segurança.

Executar:
    pytest test_security.py -v

    ou

    python test_security.py
"""

import os
import sys
import unittest

from security import (
    AuditAction,
    AuditTrailManager,
    EncryptionService,
    Permission,
    PIIProtectionService,
    PIIType,
    RBACManager,
    Role,
    SecureAccountingService,
    VaultManager,
)

# Setup de ambiente para testes
os.environ["ENCRYPTION_KEY_CURRENT"] = "test-encryption-key-32chars-min-length-required"
os.environ["HMAC_SECRET_KEY"] = "test-hmac-secret-key-32chars-min-length-required"

# Adiciona path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestVaultManager(unittest.TestCase):
    """Testes do VaultManager."""

    def setUp(self):
        self.vault = VaultManager()

    def test_singleton(self):
        """Testa padrão singleton."""
        vault2 = VaultManager()
        self.assertIs(self.vault, vault2)

    def test_get_encryption_key(self):
        """Testa obtenção de chave de criptografia."""
        key = self.vault.get_encryption_key()
        self.assertIsNotNone(key)
        self.assertGreaterEqual(len(key), 32)

    def test_get_hmac_key(self):
        """Testa obtenção de chave HMAC."""
        key = self.vault.get_hmac_key()
        self.assertIsNotNone(key)
        self.assertGreaterEqual(len(key), 32)

    def test_validate_secrets(self):
        """Testa validação de secrets."""
        self.assertTrue(self.vault.validate_secrets())

    def test_health_status(self):
        """Testa health check."""
        status = self.vault.get_health_status()
        self.assertEqual(status["status"], "healthy")
        self.assertGreater(status["secrets_loaded"], 0)


class TestEncryptionService(unittest.TestCase):
    """Testes do EncryptionService."""

    def setUp(self):
        self.enc = EncryptionService()

    def test_encrypt_decrypt_string(self):
        """Testa criptografia/descriptografia de string."""
        original = "dados sensíveis para teste"
        encrypted = self.enc.encrypt(original)
        decrypted = self.enc.decrypt(encrypted)
        self.assertEqual(original, decrypted)

    def test_encrypt_decrypt_bytes(self):
        """Testa criptografia/descriptografia de bytes."""
        original = b"binary data"
        encrypted = self.enc.encrypt(original)
        decrypted = self.enc.decrypt(encrypted)
        self.assertEqual(original.decode(), decrypted)

    def test_encrypt_dict(self):
        """Testa criptografia de dicionário."""
        data = {"nome": "João", "cp": "12345678901", "salario": 5000.00}
        encrypted = self.enc.encrypt_dict(data, ["cp", "salario"])

        # Campos criptografados devem ter prefixo ENC:
        self.assertTrue(encrypted["cp"].startswith("ENC:"))
        self.assertTrue(str(encrypted["salario"]).startswith("ENC:"))

        # Campo não criptografado permanece igual
        self.assertEqual(encrypted["nome"], "João")

    def test_decrypt_dict(self):
        """Testa descriptografia de dicionário."""
        data = {"cp": "12345678901"}
        encrypted = self.enc.encrypt_dict(data, ["cp"])
        decrypted = self.enc.decrypt_dict(encrypted)
        self.assertEqual(decrypted["cp"], "12345678901")


class TestRBACManager(unittest.TestCase):
    """Testes do RBACManager."""

    def setUp(self):
        self.rbac = RBACManager()
        # Limpa operadores (exceto SYSTEM_ADMIN)
        self.rbac._operators = {
            k: v for k, v in self.rbac._operators.items() if "SYSTEM_ADMIN" in k
        }

        # Registra operador de teste
        self.rbac.register_operator(
            operator_id="TEST_OPERATOR",
            tenant_id="TEST_TENANT",
            roles={Role.ACCOUNTANT},
        )

    def test_register_operator(self):
        """Testa registro de operador."""
        operator = self.rbac.register_operator(
            operator_id="NEW_OP", tenant_id="TENANT_123", roles={Role.VIEWER}
        )
        self.assertEqual(operator.operator_id, "NEW_OP")
        self.assertEqual(operator.tenant_id, "TENANT_123")

    def test_validate_access_success(self):
        """Testa validação de acesso bem-sucedida."""
        # Accountant tem permissão para processar folha
        result = self.rbac.validate_access(
            operator_id="TEST_OPERATOR",
            tenant_id="TEST_TENANT",
            required_permission=Permission.PROCESS_PAYROLL,
        )
        self.assertTrue(result)

    def test_validate_access_denied(self):
        """Testa negação de acesso."""
        # Accountant NÃO tem permissão para gerenciar tenants
        with self.assertRaises(PermissionError):
            self.rbac.validate_access(
                operator_id="TEST_OPERATOR",
                tenant_id="TEST_TENANT",
                required_permission=Permission.MANAGE_TENANTS,
            )

    def test_idor_detection(self):
        """Testa detecção de IDOR."""
        from security.rbac_manager import SecurityError

        # Tenta acessar recurso de outro tenant
        with self.assertRaises(SecurityError):
            self.rbac.validate_access(
                operator_id="TEST_OPERATOR",
                tenant_id="TEST_TENANT",
                required_permission=Permission.READ_SENSITIVE_DATA,
                resource_tenant_id="OTHER_TENANT",  # IDOR!
            )


class TestPIIProtectionService(unittest.TestCase):
    """Testes do PIIProtectionService."""

    def setUp(self):
        self.pii = PIIProtectionService()

    def test_mask_cpf(self):
        """Testa masking de CPF."""
        masked = self.pii.mask("12345678901", PIIType.CPF)
        self.assertEqual(masked, "123.***.***-01")

    def test_mask_email(self):
        """Testa masking de email."""
        masked = self.pii.mask("joao@email.com", PIIType.EMAIL)
        self.assertTrue(masked.startswith("joa"))
        self.assertIn("@email.com", masked)

    def test_hash_for_search(self):
        """Testa hashing para busca."""
        cpf = "12345678901"
        hash1 = self.pii.hash_for_search(cpf, PIIType.CPF)
        hash2 = self.pii.hash_for_search(cpf, PIIType.CPF)

        # Hashes iguais para mesmo valor
        self.assertEqual(hash1, hash2)

        # Hash diferente do valor original
        self.assertNotEqual(hash1, cpf)

    def test_apply_pii_masking(self):
        """Testa masking em dicionário."""
        data = {"nome": "João", "cp": "12345678901", "email": "joao@email.com"}
        masked = self.pii.apply_pii_masking(data, ["cp", "email"])

        # Nome não deve ser mascarado
        self.assertEqual(masked["nome"], "João")

        # CPF e email devem ser mascarados
        self.assertNotEqual(masked["cp"], "12345678901")
        self.assertNotEqual(masked["email"], "joao@email.com")


class TestAuditTrailManager(unittest.TestCase):
    """Testes do AuditTrailManager."""

    def setUp(self):
        self.audit = AuditTrailManager()

    def test_log_entry(self):
        """Testa registro de entrada."""
        # Registra evento
        self.audit.log(
            tenant_id="TEST_TENANT",
            operator_id="TEST_OPERATOR",
            action=AuditAction.LOGIN,
            description="Teste de login",
        )

        # Deve estar no cache
        self.assertGreater(len(self.audit._entry_cache), 0)

    def test_entry_signature(self):
        """Testa assinatura de entrada."""
        from security.audit_trail_manager import AuditEntry

        entry = AuditEntry(tenant_id="TEST", operator_id="OP", action=AuditAction.LOGIN)

        signature = self.audit._sign_entry(entry)
        self.assertIsNotNone(signature)
        self.assertGreater(len(signature), 0)

    def test_verify_entry(self):
        """Testa verificação de entrada."""
        from security.audit_trail_manager import AuditEntry

        entry = AuditEntry(tenant_id="TEST", operator_id="OP", action=AuditAction.LOGIN)

        # Assina
        entry.signature = self.audit._sign_entry(entry)

        # Verifica
        self.assertTrue(self.audit.verify_entry(entry))


class TestSecureAccountingService(unittest.TestCase):
    """Testes do SecureAccountingService."""

    def setUp(self):
        # Registra operador de teste
        rbac = RBACManager()
        rbac.register_operator(
            operator_id="TEST_ACCOUNTANT",
            tenant_id="TEST_COMPANY",
            roles={Role.ACCOUNTANT},
        )

        self.service = SecureAccountingService(
            tenant_id="TEST_COMPANY", operator_id="TEST_ACCOUNTANT"
        )

    def test_initialization(self):
        """Testa inicialização do serviço."""
        self.assertIsNotNone(self.service.vault)
        self.assertIsNotNone(self.service.encryption)
        self.assertIsNotNone(self.service.rbac)
        self.assertIsNotNone(self.service.pii)
        self.assertIsNotNone(self.service.audit)

    def test_encrypt_sensitive_data(self):
        """Testa criptografia de dados."""
        data = {"salario": 5000.00, "nome": "João"}
        encrypted = self.service.encrypt_sensitive_data(
            data, sensitive_fields=["salario"]
        )

        self.assertTrue(str(encrypted["salario"]).startswith("ENC:"))
        self.assertEqual(encrypted["nome"], "João")

    def test_mask_pii(self):
        """Testa masking de PII."""
        data = {"cp": "12345678901", "nome": "João"}
        masked = self.service.mask_pii_for_display(data, ["cp"])

        self.assertEqual(masked["cp"], "123.***.***-01")
        self.assertEqual(masked["nome"], "João")

    def test_get_security_status(self):
        """Testa obtenção de status de segurança."""
        status = self.service.get_security_status()

        self.assertIn("vault", status)
        self.assertIn("rbac", status)
        self.assertIn("pii", status)
        self.assertIn("audit", status)


def run_tests():
    """Executa todos os testes."""
    # Cria test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Adiciona todos os testes
    suite.addTests(loader.loadTestsFromTestCase(TestVaultManager))
    suite.addTests(loader.loadTestsFromTestCase(TestEncryptionService))
    suite.addTests(loader.loadTestsFromTestCase(TestRBACManager))
    suite.addTests(loader.loadTestsFromTestCase(TestPIIProtectionService))
    suite.addTests(loader.loadTestsFromTestCase(TestAuditTrailManager))
    suite.addTests(loader.loadTestsFromTestCase(TestSecureAccountingService))

    # Executa
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Retorna código de saída
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
