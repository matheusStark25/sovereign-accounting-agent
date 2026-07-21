import os
import sqlite3
import sys

# Adiciona o diretório pai ao path para permitir importações
pasta_pai = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if pasta_pai not in sys.path:
    sys.path.insert(0, pasta_pai)


# --- 1. FUNÃÃO DE BUSCA NO BANCO (Direto aqui para nÃ£o dar erro de import) ---
def recuperar_contexto(
    tema_pesquisa, *args
):  # Adicionei *args para ignorar o CNPJ se ele vier
    try:
        # Caminho absoluto baseado no local deste arquivo
        pasta_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        caminho_db = os.path.join(pasta_base, "database", "base_dp.db")

        if not os.path.exists(caminho_db):
            return f"Banco não encontrado em: {caminho_db}"

        conn = sqlite3.connect(caminho_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT conteudo FROM base_dp WHERE tema LIKE ?", (f"%{tema_pesquisa}%",)
        )
        resultado = cur.fetchone()
        conn.close()
        return (
            resultado[0] if resultado else "InformaÃ§Ã£o nÃ£o encontrada na base de DP."
        )
    except Exception as e:
        return f"Erro no banco: {e}"


# --- 2. IMPORTAÃÃES DOS OUTROS SERVIÃOS (Apenas os que existem) ---
# Se esses arquivos ainda nÃ£o existirem, o Python vai reclamar de novo.
try:
    from services.historico_service import salvar_historico
    from services.ia_service import chamar_ia
    from services.memoria_service import atualizar_memoria, recuperar_memoria

    print("✓ Serviços importados com sucesso!")
except ImportError as e:
    print(f"â ï¸ Aviso: Algum serviÃ§o ainda nÃ£o foi criado: {e}")

# --- 3. LÃGICA DO AGENTE ---


def identificar_intencao(pergunta):
    pergunta_lower = pergunta.lower()
    if any(p in pergunta_lower for p in ["fÃ©rias", "ferias"]):
        return "ferias"
    if any(p in pergunta_lower for p in ["salÃ¡rio", "salario", "pagamento"]):
        return "salario"
    if any(p in pergunta_lower for p in ["13", "decimo"]):
        return "13_salario"
    return "geral"


def processar_mensagem(pergunta, cnpj):
    # RAG: Recupera contexto usando a funÃ§Ã£o que criamos acima
    contexto_dp = recuperar_contexto(pergunta)

    # Tenta recuperar memÃ³ria (se o serviÃ§o existir)
    try:
        memoria = recuperar_memoria(cnpj)
    except BaseException:
        memoria = "Sem histÃ³rico."

    contexto_total = (
        f"CONHECIMENTO: {contexto_dp}\nMEMÃRIA: {memoria}\nPERGUNTA: {pergunta}"
    )

    # Tenta chamar IA
    try:
        resposta = chamar_ia(pergunta, contexto_total)
        salvar_historico(cnpj, pergunta, resposta)
        atualizar_memoria(cnpj, pergunta, resposta)
        return resposta
    except BaseException:
        return f"A IA encontrou isso no banco: {contexto_dp}"


# --- 4. EXECUÇÃO COMO SCRIPT PRINCIPAL (TESTE) ---
if __name__ == "__main__":
    print("=" * 50)
    print("Agente DP - Teste de Funcionamento")
    print("=" * 50)

    # Teste básico
    pergunta_teste = "Como funciona o cálculo de férias?"
    cnpj_teste = "00.000.000/0001-00"

    print(f"\nPergunta de teste: {pergunta_teste}")
    print(f"CNPJ de teste: {cnpj_teste}")

    resultado = processar_mensagem(pergunta_teste, cnpj_teste)
    print(f"\nResposta: {resultado}")
    print("\n" + "=" * 50)
