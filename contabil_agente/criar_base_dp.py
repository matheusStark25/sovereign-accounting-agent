import sqlite3

# Criar banco de dados base_dp.db
conn = sqlite3.connect("db/base_dp.db")
cur = conn.cursor()

# Criar tabela
cur.execute("""
    CREATE TABLE IF NOT EXISTS base_dp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tema TEXT,
        conteudo TEXT
    )
""")

# Dados sobre Departamento Pessoal
dados_dp = [
    {
        "tema": "Férias",
        "conteudo": """FÉRIAS: Todo empregado tem direito a 30 dias de férias após 12 meses de trabalho (período aquisitivo).
        O pagamento deve ser feito até 2 dias antes do início das férias.
        Cálculo: Salário + 1/3 constitucional.
        Exemplo: Salário R$ 3.000,00 + R$ 1.000,00 (1/3) = R$ 4.000,00 de férias.
        Pode ser fracionado em até 3 períodos, sendo um de no mínimo 14 dias e os demais de no mínimo 5 dias.""",
    },
    {
        "tema": "13º Salário",
        "conteudo": """13º SALÁRIO: Gratificação natalina paga em duas parcelas.
        1ª parcela: até 30 de novembro (metade do salário).
        2ª parcela: até 20 de dezembro (restante com descontos de INSS e IR).
        Cálculo: (Salário bruto ÷ 12) × número de meses trabalhados.
        Exemplo: Salário R$ 3.000,00, trabalhou 12 meses = R$ 3.000,00 de 13º.""",
    },
    {
        "tema": "Rescisão",
        "conteudo": """RESCISÃO DE CONTRATO: Verbas a pagar dependem do tipo de demissão.
        SEM JUSTA CAUSA: Aviso prévio, saldo salário, férias proporcionais + 1/3, 13º proporcional, FGTS + 40% multa.
        COM JUSTA CAUSA: Apenas saldo de salário e férias vencidas.
        PEDIDO DE DEMISSÃO: Saldo salário, férias proporcionais + 1/3, 13º proporcional (sem multa FGTS).
        Pagamento deve ser feito em até 10 dias após o término do contrato.""",
    },
    {
        "tema": "FGTS",
        "conteudo": """FGTS (Fundo de Garantia): Depósito mensal de 8% do salário bruto.
        Empregador deposita na conta vinculada do trabalhador na Caixa Econômica Federal.
        Saque permitido em: demissão sem justa causa, aposentadoria, doenças graves, compra de imóvel.
        Na demissão sem justa causa: direito a multa de 40% sobre o saldo do FGTS.""",
    },
    {
        "tema": "INSS",
        "conteudo": """INSS (Previdência Social): Desconto progressivo sobre o salário.
        Alíquotas 2024:
        - Até R$ 1.412,00: 7,5%
        - De R$ 1.412,01 até R$ 2.666,68: 9%
        - De R$ 2.666,69 até R$ 4.000,03: 12%
        - De R$ 4.000,04 até R$ 7.786,02: 14%
        Teto de contribuição: R$ 7.786,02""",
    },
    {
        "tema": "Vale Transporte",
        "conteudo": """VALE TRANSPORTE: Benefício obrigatório para deslocamento casa-trabalho-casa.
        Desconto máximo: 6% do salário bruto.
        Empregador paga a diferença se o custo for maior que 6%.
        Exemplo: Transporte custa R$ 300/mês, salário R$ 3.000,00, desconto R$ 180,00 (6%), empresa paga R$ 120,00.""",
    },
    {
        "tema": "Horas Extras",
        "conteudo": """HORAS EXTRAS: Trabalho além da jornada normal (8h/dia ou 44h/semana).
        Adicional mínimo: 50% sobre valor da hora normal (dias úteis).
        Adicional domingos e feriados: 100%.
        Cálculo da hora: Salário mensal ÷ 220 horas.
        Exemplo: Salário R$ 3.000,00, hora normal = R$ 13,64, hora extra 50% = R$ 20,46.""",
    },
    {
        "tema": "Adicional Noturno",
        "conteudo": """ADICIONAL NOTURNO: Trabalho entre 22h e 5h.
        Adicional: mínimo 20% sobre a hora diurna.
        Hora noturna reduzida: 52min30s (não 60min).
        Cálculo: (Salário ÷ 220) × 1,20 × número de horas noturnas.""",
    },
    {
        "tema": "DSR",
        "conteudo": """DSR (Descanso Semanal Remunerado): Direito a folga semanal remunerada,
 preferencialmente aos domingos.
        Pagamento: já incluído no salário mensal.
        Perda do DSR: faltas injustificadas durante a semana.
        Para horistas e comissionados: calcula-se separadamente com base nos dias úteis.""",
    },
    {
        "tema": "Aviso Prévio",
        "conteudo": """AVISO PRÉVIO: Comunicação antecipada de término do contrato.
        Prazo mínimo: 30 dias + 3 dias por ano trabalhado (máximo 90 dias).
        Trabalhado: redução de 2h/dia ou 7 dias corridos no final.
        Indenizado: empresa paga sem trabalhar.
        Exemplo: 5 anos de empresa = 30 + 15 dias = 45 dias de aviso.""",
    },
]

# Inserir dados
for item in dados_dp:
    cur.execute(
        "INSERT INTO base_dp (tema, conteudo) VALUES (?, ?)",
        (item["tema"], item["conteudo"]),
    )

conn.commit()
conn.close()

print("✅ Base de dados criada com sucesso!")
print("📊 Temas adicionados:")
for item in dados_dp:
    print(f"   - {item['tema']}")
