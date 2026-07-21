from flask import Blueprint  # type: ignore
from services.historico_service import recuperar_historico  # type: ignore

painel_bp = Blueprint("painel_bp", __name__)


@painel_bp.route("/painel/historico")
def painel():
    dados = recuperar_historico()
    html = "<h2>Histórico DP</h2><ul>"
    for d in dados:
        html += f"<li>{d[0]} | {d[3]}<br>Pergunta: {d[1]}<br>Resposta: {d[2]}</li>"
    html += "</ul>"
    return html
