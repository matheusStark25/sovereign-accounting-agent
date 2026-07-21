"""
TESTE DE SCRAPING REAL - Busca automÃ¡tica de tabelas INSS/IRRF do governo
"""

import re

import requests


def testar_scraping_inss():
    """Testa scraping do Portal Gov.br para INSS"""
    print("\n" + "=" * 70)
    print("TESTANDO SCRAPING INSS - Portal Gov.br")
    print("=" * 70)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    urls = [
        "https://www.gov.br/inss/pt-br/direitos-e-deveres/inscricao-e-contribuicao/tabela-de-contribuicao-mensal",
        (
            "https://www.gov.br/trabalho-e-previdencia/pt-br/assuntos/previdencia-social/saiba-mais/legislacao-e-regulamentacao/t"
            "abela-de-contribuicao-ao-inss"
        ),
    ]

    for url in urls:
        print(f"\nð¡ Buscando: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=30)
            print(f"â Status: {response.status_code}")

            if response.status_code == 200:
                html = response.text

                # Busca salÃ¡rio mÃ­nimo
                match_sm = re.search(
                    r"salÃ¡rio mÃ­nimo.*?R\$\s*([\d\.,]+)", html, re.IGNORECASE
                )
                if match_sm:
                    sm = match_sm.group(1).replace(".", "").replace(",", ".")
                    print(f"ð° SalÃ¡rio mÃ­nimo encontrado: R$ {sm}")

                # Busca teto INSS
                match_teto = re.search(r"teto.*?R\$\s*([\d\.,]+)", html, re.IGNORECASE)
                if match_teto:
                    teto = match_teto.group(1).replace(".", "").replace(",", ".")
                    print(f"ð Teto INSS encontrado: R$ {teto}")

                # Busca faixas
                padrao = r"(?:de|atÃ©)\s+R\$\s*([\d\.,]+)(?:\s+(?:atÃ©|a)\s+R\$\s*([\d\.,]+))?\s*[-â]\s*([\d,]+)%"
                matches = list(re.finditer(padrao, html, re.IGNORECASE))

                print(f"ð Encontradas {len(matches)} faixas de contribuiÃ§Ã£o:")
                for i, match in enumerate(matches[:5]):  # Mostra atÃ© 5
                    valor_max = match.group(2) if match.group(2) else match.group(1)
                    aliquota = match.group(3)
                    print(f"  {i + 1}. AtÃ© R$ {valor_max} - {aliquota}%")

                if len(matches) >= 4:
                    print("\nâ SUCESSO: Conseguiu extrair tabela INSS!")
                    return True
                else:
                    print(
                        f"\nâ ï¸ Encontrou apenas {len(matches)} faixas (precisa de 4+)"
                    )

        except Exception as e:
            print(f"â Erro: {e}")

    return False


def testar_scraping_irrf():
    """Testa scraping da Receita Federal para IRRF"""
    print("\n" + "=" * 70)
    print("TESTANDO SCRAPING IRRF - Receita Federal")
    print("=" * 70)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    urls = [
        "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/tributos/irpf-imposto-de-renda-pessoa-fisica",
        "https://www.contabilizei.com.br/contabilidade-online/tabela-irrf/",
    ]

    for url in urls:
        print(f"\nð¡ Buscando: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=30)
            print(f"â Status: {response.status_code}")

            if response.status_code == 200:
                html = response.text

                # Busca faixa isenta
                match_isento = re.search(
                    r"isento.*?(?:atÃ©|de)\s+R\$\s*([\d\.,]+)", html, re.IGNORECASE
                )
                if match_isento:
                    valor = match_isento.group(1).replace(".", "").replace(",", ".")
                    print(f"ðµ Faixa isenta atÃ©: R$ {valor}")

                # Busca faixas tributadas
                padrao = r"(?:de|atÃ©)\s+R\$\s*([\d\.,]+)\s+(?:atÃ©|a)\s+R\$\s*([\d\.,]+)\s*[-â]\s*(\d+,?\d*)%(?:\s*[-â]\s*parcela.*?R\$\s*([\d\.,]+))?"
                matches = list(re.finditer(padrao, html, re.IGNORECASE))

                print(f"ð Encontradas {len(matches)} faixas de IR:")
                for i, match in enumerate(matches[:5]):
                    min_val = match.group(1)
                    max_val = match.group(2)
                    aliq = match.group(3)
                    ded = match.group(4) if match.group(4) else "0,00"
                    print(
                        f"  {i + 1}. De R$ {min_val} atÃ© R$ {max_val} - {aliq}% (deduÃ§Ã£o: R$ {ded})"
                    )

                # Busca deduÃ§Ã£o por dependente
                match_dep = re.search(
                    r"dependente.*?R\$\s*([\d\.,]+)", html, re.IGNORECASE
                )
                if match_dep:
                    dep_val = match_dep.group(1)
                    print(
                        f"ð¨âð©âð§âð¦ DeduÃ§Ã£o por dependente: R$ {dep_val}"
                    )

                if len(matches) >= 4:
                    print("\nâ SUCESSO: Conseguiu extrair tabela IRRF!")
                    return True
                else:
                    print(
                        f"\nâ ï¸ Encontrou apenas {len(matches)} faixas (precisa de 4+)"
                    )

        except Exception as e:
            print(f"â Erro: {e}")

    return False


if __name__ == "__main__":
    print("\nð TESTE DE SCRAPING AUTOMÃTICO DAS TABELAS DO GOVERNO")
    print("=" * 70)

    # Testa INSS
    sucesso_inss = testar_scraping_inss()

    # Testa IRRF
    sucesso_irrf = testar_scraping_irrf()

    print("\n" + "=" * 70)
    print("RESUMO DOS TESTES")
    print("=" * 70)
    print(f"â INSS: {'FUNCIONOU' if sucesso_inss else 'â FALHOU'}")
    print(f"â IRRF: {'FUNCIONOU' if sucesso_irrf else 'â FALHOU'}")

    if sucesso_inss and sucesso_irrf:
        print("\nð PERFEITO! O scraping estÃ¡ funcionando!")
        print("As tabelas PODEM ser atualizadas automaticamente TODO ANO!")
    else:
        print("\nâ ï¸ Alguns scraping falharam. Precisa ajustar os padrÃµes regex.")
