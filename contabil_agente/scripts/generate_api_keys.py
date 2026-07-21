"""
Gerador de API Keys Seguras para as Empresas
"""

import secrets
import string


def generate_api_key(prefix: str = "key", length: int = 32) -> str:
    """Gera API key aleatória e segura"""
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}_{random_part}"


def generate_all_empresa_keys():
    """Gera API keys para todas as 15 empresas"""
    empresas = [
        "ELITE_SENIOR",
        "CONTABIL_ABC",
        "FISCAL_PRO",
        "EMPRESA_04",
        "EMPRESA_05",
        "EMPRESA_06",
        "EMPRESA_07",
        "EMPRESA_08",
        "EMPRESA_09",
        "EMPRESA_10",
        "EMPRESA_11",
        "EMPRESA_12",
        "EMPRESA_13",
        "EMPRESA_14",
        "EMPRESA_15",
    ]

    print("# API Keys Geradas - Adicionar ao .env\n")

    for empresa in empresas:
        key = generate_api_key(prefix="sk", length=48)
        print(f"API_KEY_{empresa}={key}")

    print("\n# Secret Key para Flask")
    secret_key = secrets.token_urlsafe(64)
    print(f"SECRET_KEY={secret_key}")


if __name__ == "__main__":
    generate_all_empresa_keys()
