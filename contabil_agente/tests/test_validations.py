"""
Testes para funções de validação do chat_service
"""

import pytest
from services.chat_service import validar_cpf, validar_data, validar_nome


class TestValidations:
    """Testes das funções de validação"""

    def test_validar_cpf_valido(self):
        """Testa CPF válido"""
        assert validar_cpf("123.456.789-00") is True
        assert validar_cpf("12345678900") is True

    def test_validar_cpf_invalido(self):
        """Testa CPF inválido"""
        assert validar_cpf("123.456.789") is False  # poucos dígitos
        assert validar_cpf("abc.def.ghi-jk") is False  # não numérico
        assert validar_cpf("") is False  # vazio
        assert validar_cpf(None) is False  # None

    def test_validar_data_valida(self):
        """Testa data válida"""
        assert validar_data("31/12/2023") is True
        assert validar_data("01-01-2024") is True

    def test_validar_data_invalida(self):
        """Testa data inválida"""
        assert validar_data("31/02/2023") is False  # data inexistente
        assert validar_data("2023/12/31") is False  # formato errado
        assert validar_data("abc/def/ghi") is False  # não numérico
        assert validar_data("") is False  # vazio

    def test_validar_nome_valido(self):
        """Testa nome válido"""
        assert validar_nome("João Silva") is True
        assert validar_nome("Maria José Santos") is True
        assert validar_nome("José da Silva") is True

    def test_validar_nome_invalido(self):
        """Testa nome inválido"""
        assert validar_nome("João") is False  # só um nome
        assert validar_nome("João123") is False  # números
        assert validar_nome("João@Silva") is False  # caracteres especiais
        assert validar_nome("") is False  # vazio
        assert validar_nome("   ") is False  # só espaços
        assert validar_nome(None) is False  # None


if __name__ == "__main__":
    pytest.main([__file__])
