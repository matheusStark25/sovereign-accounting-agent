"""
TESTE V2 - Analisa HTML dos sites para ver como extrair dados
"""

import re

import requests


def analisar_html_inss():
    """Analisa HTML do Gov.br INSS"""
    print("\n" + "=" * 70)
    print("ANALISANDO HTML - INSS")
    print("=" * 70)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    url = "https://www.gov.br/inss/pt-br/direitos-e-deveres/inscricao-e-contribuicao/tabela-de-contribuicao-mensal"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            html = response.text

            # Procura todas as menções de valores em reais
            valores = re.findall(r"R\$\s*[\d\.,]+", html)
            print("\n💰 Valores encontrados (primeiros 20):")
            for i, val in enumerate(valores[:20]):
                print(f"  {i + 1}. {val}")

            # Procura percentuais
            percentuais = re.findall(r"\d+[.,]?\d*\s*%", html)
            print("\n📊 Percentuais encontrados (primeiros 10):")
            for i, perc in enumerate(percentuais[:10]):
                print(f"  {i + 1}. {perc}")

            # Busca por padrões de tabela
            print("\n📋 Buscando padrões de tabela...")

            # Padrão 1: Valor + percentual próximos
            padrao1 = r"(R\$\s*[\d\.,]+).*?(\d+[.,]?\d*\s*%)"
            matches1 = re.findall(padrao1, html[:5000])  # Primeiros 5000 chars
            if matches1:
                print(f"  Padrão 'Valor + %' encontrado {len(matches1)} vezes:")
                for i, (val, perc) in enumerate(matches1[:5]):
                    print(f"    {i + 1}. {val} → {perc}")

            # Salva amostra do HTML
            with open("amostra_html_inss.txt", "w", encoding="utf-8") as f:
                f.write(html[:10000])  # Primeiros 10k chars
            print("\n💾 Amostra salva em: amostra_html_inss.txt")

    except Exception as e:
        print(f"❌ Erro: {e}")


def analisar_html_irrf():
    """Analisa HTML da Receita Federal IRRF"""
    print("\n" + "=" * 70)
    print("ANALISANDO HTML - IRRF")
    print("=" * 70)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    url = "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/tributos/irpf-imposto-de-renda-pessoa-fisica"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            html = response.text

            # Procura isento
            if re.search(r"isento", html, re.IGNORECASE):
                print("✅ Palavra 'isento' encontrada!")

            # Procura valores
            valores = re.findall(r"R\$\s*[\d\.,]+", html)
            print("\n💰 Valores encontrados (primeiros 15):")
            for i, val in enumerate(valores[:15]):
                print(f"  {i + 1}. {val}")

            # Procura percentuais
            percentuais = re.findall(r"\d+[.,]?\d*\s*%", html)
            print("\n📊 Percentuais encontrados (primeiros 10):")
            for i, perc in enumerate(percentuais[:10]):
                print(f"  {i + 1}. {perc}")

            # Busca "dedução"
            match_ded = re.findall(
                r"dedu[çc][ãa]o.*?R\$\s*[\d\.,]+", html, re.IGNORECASE
            )
            if match_ded:
                print("\n💵 Menções de dedução:")
                for i, ded in enumerate(match_ded[:5]):
                    print(f"  {i + 1}. {ded[:100]}...")

            # Salva amostra
            with open("amostra_html_irrf.txt", "w", encoding="utf-8") as f:
                f.write(html[:10000])
            print("\n💾 Amostra salva em: amostra_html_irrf.txt")

    except Exception as e:
        print(f"❌ Erro: {e}")


def testar_fonte_alternativa():
    """Testa Sage Contabilidade"""
    print("\n" + "=" * 70)
    print("TESTANDO FONTE ALTERNATIVA - Sage")
    print("=" * 70)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    urls = [
        "https://blog.sage.com.br/tabela-inss-2026/",
        "https://blog.sage.com.br/tabela-irrf-2026/",
        "https://www.jornalcontabil.com.br/tabela-inss-2026/",
        "https://www.jornalcontabil.com.br/tabela-irrf-2026/",
    ]

    for url in urls:
        print(f"\n📡 Testando: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=20)
            print(f"  Status: {response.status_code}")

            if response.status_code == 200:
                html = response.text
                valores = re.findall(r"R\$\s*[\d\.,]+", html)
                percentuais = re.findall(r"\d+[.,]?\d*\s*%", html)
                print(f"  ✅ Valores: {len(valores)} | Percentuais: {len(percentuais)}")

        except Exception as e:
            print(f"  ❌ Erro: {e}")


if __name__ == "__main__":
    print("\n🔍 ANÁLISE DE HTML PARA SCRAPING")
    print("Vamos ver como os sites estruturam os dados...")

    analisar_html_inss()
    analisar_html_irrf()
    testar_fonte_alternativa()

    print("\n✅ Análise concluída! Verifique os arquivos .txt gerados.")
