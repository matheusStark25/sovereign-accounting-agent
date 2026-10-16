"""
Testes da API REST - Endpoint de Rescisão
Valida RBAC, Multi-tenancy, Validações e Cálculos
"""

import json
import sys
import unittest
from pathlib import Path

from app_api import app

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRescisaoAPI(unittest.TestCase):
    """Testes do endpoint POST /api/v1/calculo/rescisao"""

    def setUp(self):
        """Configura cliente de teste"""
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Headers padrão de autenticação
        self.auth_headers = {
            "X-User-ID": "usr_test_001",
            "X-Username": "joao.contador",
            "X-User-Email": "joao@empresa.com",
            "X-User-Roles": "contador,admin",
            "X-Tenant-ID": "tenant_empresa_xyz",
            "Content-Type": "application/json",
        }

        # Payload válido padrão
        self.valid_payload = {
            "salario_base": 3000.00,
            "data_admissao": "2020-01-15",
            "data_demissao": "2026-02-04",
            "motivo_desligamento": "sem_justa_causa",
            "aviso_previo_indenizado": True,
            "saldo_fgts": 5000.00,
            "tem_periculosidade": False,
            "num_dependentes": 0,
        }

    def test_health_check(self):
        """Testa endpoint de health check"""
        response = self.client.get("/api/v1/calculo/health")
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "rescisao_api")

    def test_rescisao_sucesso_basico(self):
        """Testa cálculo de rescisão bem-sucedido"""
        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(self.valid_payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertTrue(data["success"])
        self.assertIn("data", data)
        self.assertIn("metadata", data)

        # Validar estrutura de dados
        resultado = data["data"]
        self.assertIn("verbas_rescisao", resultado)
        self.assertIn("total_bruto", resultado)
        self.assertIn("total_liquido", resultado)
        self.assertIn("descontos", resultado)

        # Validar valores (total líquido > 0)
        self.assertGreater(resultado["total_liquido"], 0)

        # Validar metadata
        metadata = data["metadata"]
        self.assertEqual(metadata["user_id"], "usr_test_001")
        self.assertEqual(metadata["tenant_id"], "tenant_empresa_xyz")
        self.assertEqual(metadata["motivo_desligamento"], "sem_justa_causa")

    def test_rescisao_com_periculosidade(self):
        """Testa rescisão com adicional de periculosidade"""
        payload = self.valid_payload.copy()
        payload["tem_periculosidade"] = True
        payload["salario_base"] = 4000.00

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        resultado = data["data"]

        # Periculosidade deve estar nos detalhes
        detalhes = resultado["detalhes"]
        self.assertEqual(detalhes["tem_periculosidade"], True)
        self.assertEqual(detalhes["periculosidade_mensal"], 1200.00)

        # Salário total = base + periculosidade
        self.assertEqual(detalhes["salario_total"], 5200.00)

    def test_erro_sem_autenticacao(self):
        """Testa acesso sem autenticação"""
        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(self.valid_payload),
            headers={"Content-Type": "application/json"},  # Sem headers de auth
        )

        self.assertEqual(response.status_code, 401)

        data = json.loads(response.data)
        self.assertFalse(data.get("success", True))
        self.assertEqual(data["status_code"], 401)
        self.assertIn("Autenticação", data["message"])

    def test_erro_role_invalida(self):
        """Testa acesso com role inválida"""
        headers = self.auth_headers.copy()
        headers["X-User-Roles"] = "usuario_comum"  # Não é contador nem admin

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(self.valid_payload),
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

        data = json.loads(response.data)
        self.assertEqual(data["status_code"], 403)
        self.assertIn("Acesso negado", data["message"])

    def test_erro_salario_invalido(self):
        """Testa validação de salário inválido"""
        payload = self.valid_payload.copy()
        payload["salario_base"] = "abc"  # String inválida

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["field"], "salario_base")
        self.assertIn("número válido", data["message"])

    def test_erro_salario_abaixo_minimo(self):
        """Testa salário abaixo do salário mínimo"""
        payload = self.valid_payload.copy()
        payload["salario_base"] = 1000.00  # Abaixo de R$ 1.412

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertEqual(data["field"], "salario_base")
        self.assertIn("1412", data["message"])

    def test_erro_data_invalida(self):
        """Testa formato de data inválido"""
        payload = self.valid_payload.copy()
        payload["data_admissao"] = (
            "15/01/2020"  # Formato errado (deve ser YYYY-MM-DD ou DD/MM/YYYY)
        )
        payload["data_admissao"] = "invalid-date"

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertEqual(data["field"], "data_admissao")
        self.assertIn("formato", data["message"].lower())

    def test_erro_demissao_antes_admissao(self):
        """Testa demissão anterior à admissão"""
        payload = self.valid_payload.copy()
        payload["data_admissao"] = "2025-01-01"
        payload["data_demissao"] = "2020-01-01"  # Antes da admissão

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertEqual(data["field"], "data_demissao")
        self.assertIn("posterior", data["message"])

    def test_erro_motivo_invalido(self):
        """Testa motivo de desligamento inválido"""
        payload = self.valid_payload.copy()
        payload["motivo_desligamento"] = "aposentadoria"  # Não existe

        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertEqual(data["field"], "motivo_desligamento")
        self.assertIn("sem_justa_causa", data["message"])

    def test_utf8_encoding(self):
        """Testa se resposta suporta UTF-8 (acentuação portuguesa)"""
        response = self.client.post(
            "/api/v1/calculo/rescisao",
            data=json.dumps(self.valid_payload),
            headers=self.auth_headers,
        )

        # Verificar que não há erro de encoding
        data = json.loads(response.data.decode("utf-8"))
        self.assertTrue(data["success"])


def suite():
    """Cria suite de testes"""
    loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()
    test_suite.addTests(loader.loadTestsFromTestCase(TestRescisaoAPI))
    return test_suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
