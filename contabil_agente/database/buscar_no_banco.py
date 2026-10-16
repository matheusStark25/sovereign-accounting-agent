import sqlite3


def buscar_no_banco(tema_pesquisa):
    try:
        conn = sqlite3.connect("database/base_dp.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT conteudo FROM base_dp WHERE tema LIKE ?", (f"%{tema_pesquisa}%",)
        )
        resultado = cur.fetchone()
        conn.close()
        return resultado[0] if resultado else "Informação não encontrada."
    except Exception as e:
        return f"Erro no banco: {e}"
