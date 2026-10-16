import os
import sqlite3

# 1. GARANTE QUE A PASTA EXISTE (O segredo que estava faltando)
if not os.path.exists("db"):
    os.makedirs("db")
    print("📂 Pasta 'db' criada com sucesso!")

# 2. CONECTAR AO BANCO
# Agora ele não vai dar erro de "pasta não encontrada"
conn = sqlite3.connect("db/base_dp.db")
cur = conn.cursor()

# 3. CRIAR TABELA
cur.execute("""
    CREATE TABLE IF NOT EXISTS base_dp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tema TEXT,
        conteudo TEXT
    )
""")

# Dados sobre Departamento Pessoal
dados_dp = [
    {"tema": "Férias", "conteudo": "FÉRIAS: Todo empregado tem direito a 30 dias..."},
    {
        "tema": "13º Salário",
        "conteudo": "13º SALÁRIO: Gratificação natalina paga em duas parcelas...",
    },
    {
        "tema": "Rescisão",
        "conteudo": "RESCISÃO DE CONTRATO: Verbas a pagar dependem do tipo de demissão...",
    },
    {"tema": "FGTS", "conteudo": "FGTS (Fundo de Garantia): Depósito mensal de 8%..."},
    {"tema": "INSS", "conteudo": "INSS (Previdência Social): Desconto progressivo..."},
    {
        "tema": "Vale Transporte",
        "conteudo": "VALE TRANSPORTE: Benefício obrigatório...",
    },
    {
        "tema": "Horas Extras",
        "conteudo": "HORAS EXTRAS: Trabalho além da jornada normal...",
    },
    {
        "tema": "Adicional Noturno",
        "conteudo": "ADICIONAL NOTURNO: Trabalho entre 22h e 5h...",
    },
    {
        "tema": "DSR",
        "conteudo": "DSR (Descanso Semanal Remunerado): Direito a folga...",
    },
    {"tema": "Aviso Prévio", "conteudo": "AVISO PRÉVIO: Comunicação antecipada..."},
]

# 4. LIMPAR A TABELA ANTES DE INSERIR (Para não duplicar dados se você rodar 2 vezes)
cur.execute("DELETE FROM base_dp")

# 5. INSERIR DADOS
for item in dados_dp:
    cur.execute(
        "INSERT INTO base_dp (tema, conteudo) VALUES (?, ?)",
        (item["tema"], item["conteudo"]),
    )

conn.commit()
conn.close()

print("\n✅ BANCO DE DADOS PRONTO!")
print("Local do arquivo: database/base_dp.db")
