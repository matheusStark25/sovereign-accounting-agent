"""
ATUALIZADOR DE TABELAS OFICIAIS - INSS/IRRF
===========================================

Este script atualiza as tabelas oficiais de INSS e IRRF com os valores
OFICIAIS publicados pelo governo.

â ï¸ IMPORTANTE:
- Use APENAS valores OFICIAIS do Governo Federal
- NÃO calcule valores proporcionalmente
- Fonte: Receita Federal / MinistÃ©rio do Trabalho
- Atualize TODO ANO quando o governo publicar novas tabelas

ð Fontes Oficiais:
- INSS: https://www.gov.br/inss/
- IRRF: https://www.gov.br/receitafederal/
"""

import json
from datetime import datetime

# ========================================
# TABELAS OFICIAIS 2026
# ========================================
# â ï¸ ATUALIZE AQUI com valores OFICIAIS!
# ========================================

ANO = 2026
SALARIO_MINIMO = 1518.00  # Decreto nº XXXX/2025

# INSS - Tabela Progressiva 2026
# Fonte: Portaria Interministerial MPS/MF nÂº XX/2026
FAIXAS_INSS = [
    {
        "min": 0.00,
        "max": 1518.00,  # Até 1 salário mínimo
        "aliquota": 0.075,  # 7,5%
        "deducao": 0.00,
        "descricao": "Até 1 salário mínimo - 7,5%",
    },
    {
        "min": 1518.01,
        "max": 2427.35,
        "aliquota": 0.09,  # 9%
        "deducao": 0.00,
        "descricao": "De R$ 1.518,01 atÃ© R$ 2.427,35 - 9%",
    },
    {
        "min": 2427.36,
        "max": 3641.03,
        "aliquota": 0.12,  # 12%
        "deducao": 0.00,
        "descricao": "De R$ 2.427,36 atÃ© R$ 3.641,03 - 12%",
    },
    {
        "min": 3641.04,
        "max": 8157.41,  # Teto do INSS
        "aliquota": 0.14,  # 14%
        "deducao": 0.00,
        "descricao": "De R$ 3.641,04 até R$ 8.157,41 (teto) - 14%",
    },
]

# IRRF - Tabela Progressiva 2026
# Fonte: Lei nÂº 13.149/2015 com atualizaÃ§Ãµes
FAIXAS_IRRF = [
    {
        "min": 0.00,
        "max": 2259.20,
        "aliquota": 0.00,  # Isento
        "deducao": 0.00,
        "descricao": "Isento - AtÃ© R$ 2.259,20",
    },
    {
        "min": 2259.21,
        "max": 2828.65,
        "aliquota": 0.075,  # 7,5%
        "deducao": 169.44,
        "descricao": "De R$ 2.259,21 atÃ© R$ 2.828,65 - 7,5%",
    },
    {
        "min": 2828.66,
        "max": 3751.05,
        "aliquota": 0.15,  # 15%
        "deducao": 381.44,
        "descricao": "De R$ 2.828,66 atÃ© R$ 3.751,05 - 15%",
    },
    {
        "min": 3751.06,
        "max": 4664.68,
        "aliquota": 0.225,  # 22,5%
        "deducao": 662.77,
        "descricao": "De R$ 3.751,06 atÃ© R$ 4.664,68 - 22,5%",
    },
    {
        "min": 4664.69,
        "max": 999999999.99,
        "aliquota": 0.275,  # 27,5%
        "deducao": 896.00,
        "descricao": "Acima de R$ 4.664,68 - 27,5%",
    },
]

DEDUCAO_DEPENDENTE_IRRF = 189.59

# ========================================
# FUNÃÃES
# ========================================


def validar_tabelas():
    """Valida se as tabelas estÃ£o corretas"""
    print("ð Validando tabelas...")

    # Valida INSS
    assert len(FAIXAS_INSS) >= 4, "â INSS deve ter pelo menos 4 faixas"
    for i, faixa in enumerate(FAIXAS_INSS):
        assert 0 <= faixa["aliquota"] <= 0.30, f"â INSS faixa {i}: alÃ­quota invÃ¡lida"
        if i > 0:
            assert (
                faixa["min"] > FAIXAS_INSS[i - 1]["max"]
            ), f"â INSS faixa {i}: valores nÃ£o crescentes"

    # Valida IRRF
    assert len(FAIXAS_IRRF) >= 5, "â IRRF deve ter pelo menos 5 faixas"
    for i, faixa in enumerate(FAIXAS_IRRF):
        assert 0 <= faixa["aliquota"] <= 0.30, f"â IRRF faixa {i}: alÃ­quota invÃ¡lida"

    print("â Tabelas validadas!")


def gerar_arquivo_json():
    """Gera arquivo JSON com tabelas oficiais"""
    dados = {
        "ano": ANO,
        "fonte": "Receita Federal do Brasil / MinistÃ©rio do Trabalho",
        "atualizado_em": datetime.now().strftime("%Y-%m-%d"),
        "salario_minimo": SALARIO_MINIMO,
        "inss": {
            "descricao": f"Tabela INSS {ANO} - ContribuiÃ§Ã£o PrevidenciÃ¡ria",
            "faixas": FAIXAS_INSS,
            "teto_maximo": FAIXAS_INSS[-1]["max"],
            "observacao": "Valores progressivos - cada faixa incide apenas sobre o valor dentro dela",
        },
        "irrf": {
            "descricao": f"Tabela IRRF {ANO} - Imposto de Renda Retido na Fonte",
            "faixas": FAIXAS_IRRF,
            "deducao_dependente": DEDUCAO_DEPENDENTE_IRRF,
            "observacao": "FÃ³rmula: (Base de CÃ¡lculo Ã AlÃ­quota) - Parcela a Deduzir",
        },
        "fgts": {
            "aliquota_mensal": 0.08,
            "multa_rescisao_sem_justa_causa": 0.40,
            "descricao": "8% mensal sobre o salÃ¡rio bruto + 40% de multa em rescisÃ£o sem justa causa",
        },
        "legislacao": {
            "inss": f"Portaria Interministerial MPS/MF nÂº XX/{ANO}",
            "irr": "Lei nÂº 13.149/2015 com atualizaÃ§Ãµes",
            "fgts": "Lei nÂº 8.036/1990",
        },
        "aviso": "IMPORTANTE: Estas tabelas devem ser atualizadas TODO ANO com os valores OFICIAIS publicados pelo governo. NÃO calcule proporcionalmente - use apenas valores OFICIAIS!",
    }

    arquivo = f"tabelas_oficiais_{ANO}.json"
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"â Arquivo '{arquivo}' gerado com sucesso!")
    return arquivo


def exibir_resumo():
    """Exibe resumo das tabelas"""
    print("\n" + "=" * 60)
    print(f"TABELAS OFICIAIS {ANO}")
    print("=" * 60)

    print(f"\nð° SalÃ¡rio MÃ­nimo: R$ {SALARIO_MINIMO:,.2f}")

    print(f"\nð INSS ({len(FAIXAS_INSS)} faixas):")
    for faixa in FAIXAS_INSS:
        print(
            f"  â¢ R$ {faixa['min']:>8,.2f} a R$ {faixa['max']:>10,.2f} â {faixa['aliquota'] * 100:>5.2f}%"
        )

    print(f"\nð IRRF ({len(FAIXAS_IRRF)} faixas):")
    for faixa in FAIXAS_IRRF:
        if faixa["aliquota"] == 0:
            print(
                f"  â¢ R$ {faixa['min']:>8,.2f} a R$ {faixa['max']:>10,.2f} â ISENTO"
            )print(
                f"  â¢ R$ {faixa['min']:>8,.2f} a R$ {faixa['max']:>10,.2f} â {faixa['aliquota'] * 100:>5.2f}% (deduz R$ {faixa['deducao']:.2f})"
            )

    print(
        f"\nð¨âð©âð§âð¦ DeduÃ§Ã£o por dependente (IRRF): R$ {DEDUCAO_DEPENDENTE_IRRF:,.2f}"
    )
    print("=" * 60)


# ========================================
# EXECUÃÃO
# ========================================


if __name__ == "__main__":
    print(f"""
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â  ATUAL
        IZADOR DE TABELAS OFICIAIS - INSS/IRRF {ANO}     â
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
    """)

    try
    :
        validar_tabelas()
        exibir_resumo()
        arquivo = gerar_arquivo_json()

        print("\nâ SUCESSO!")
        print(f"\nð Arquivo gerado: {arquivo}")
        print("\nð PrÃ³ximos passos:")
        print("   1. Copie o arquivo para a pasta do agente contÃ¡bil")
        print("   2. Reinicie o servidor")
        print("   3. As tabelas oficiais serÃ£o carregadas automaticamente!")

        print("\nâ ï¸  LEMBRE-SE:")
        print("   â¢ Atualize este script TODO ANO")
        print("   â¢ Use APENAS valores OFICIAIS do governo")
        print("   â¢ NÃO calcule valores proporcionalmente")

    except AssertionError as e:
        print(f"\nâ ERRO: {e}")
        print("Corrija os valores e tente novamente!")
    except Exception as e:
        print(f"\nâ ERRO INESPERADO: {e}")
