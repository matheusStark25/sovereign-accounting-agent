"""
Blueprint para Dashboard de Auditoria - Endpoints REST
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

auditoria_bp = Blueprint("auditoria", __name__, url_prefix="/api/auditoria")


def registrar_blueprints(app, governanca_manager):
    """Registra blueprints de auditoria na aplicação Flask."""

    @auditoria_bp.route("/dashboard/estatisticas", methods=["GET"])
    def get_estatisticas():
        """Endpoint para obter estatísticas do dashboard."""
        try:
            horas = request.args.get("horas", 24, type=int)
            stats = governanca_manager["dashboard"].obter_estatisticas(horas)
            return jsonify(stats), 200
        except Exception as e:
            logger.exception(f"Erro ao obter estatísticas: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/dashboard/historico", methods=["GET"])
    def get_historico():
        """Endpoint para obter histórico de operações."""
        try:
            limite = request.args.get("limite", 50, type=int)
            historico = governanca_manager["dashboard"].obter_historico_resumido(limite)
            return jsonify({"historico": historico}), 200
        except Exception as e:
            logger.exception(f"Erro ao obter histórico: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/metrics", methods=["GET"])
    def get_metrics():
        """Endpoint de observabilidade (JSON) com degradação controlada."""
        try:
            stats = governanca_manager["dashboard"].obter_estatisticas(horas=24) or {}
            historico = (
                governanca_manager["dashboard"].obter_historico_resumido(limite=10)
                or []
            )
            alertas = (
                governanca_manager["detector_anomalias"].listar_alertas_ativos() or []
            )
            pendentes = governanca_manager["gestor_threshold"].listar_pendentes() or []

            degradado = bool(stats.get("degradado")) or not bool(stats)

            payload = {
                "governanca_disponivel": True,
                "degradado": degradado,
                "stats": stats,
                "totais": {
                    "alertas_ativos": len(alertas),
                    "aprovacoes_pendentes": len(pendentes),
                    "historico_recente": len(historico),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return jsonify(payload), 200
        except Exception as e:
            logger.exception(f"Erro em /metrics: {str(e)}")
            return (
                jsonify(
                    {
                        "governanca_disponivel": False,
                        "degradado": True,
                        "erro": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                503,
            )

    @auditoria_bp.route("/alertas/ativos", methods=["GET"])
    def get_alertas_ativos():
        """Endpoint para obter alertas ativos."""
        try:
            alertas = governanca_manager["detector_anomalias"].listar_alertas_ativos()
            return jsonify({"alertas": alertas, "total": len(alertas)}), 200
        except Exception as e:
            logger.exception(f"Erro ao obter alertas: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/alertas/<id_alerta>/resolver", methods=["POST"])
    def resolver_alerta(id_alerta):
        """Endpoint para marcar um alerta como resolvido."""
        try:
            sucesso = governanca_manager["detector_anomalias"].marcar_alerta_resolvido(
                id_alerta
            )
            return jsonify({"sucesso": sucesso}), 200 if sucesso else 404
        except Exception as e:
            logger.exception(f"Erro ao resolver alerta: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/aprovacoes/pendentes", methods=["GET"])
    def get_aprovacoes_pendentes():
        """Endpoint para obter aprovações pendentes."""
        try:
            pendentes = governanca_manager["gestor_threshold"].listar_pendentes()
            return jsonify({"pendentes": pendentes, "total": len(pendentes)}), 200
        except Exception as e:
            logger.exception(f"Erro ao obter aprovações: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/aprovacoes/<id_aprovacao>/aprovar", methods=["POST"])
    def aprovar_decisao(id_aprovacao):
        """Endpoint para aprovar uma decisão pendente."""
        try:
            data = request.get_json()
            usuario_aprovador = data.get("usuario_aprovador", "admin")
            motivo = data.get("motivo", "")

            sucesso = governanca_manager["gestor_threshold"].aprovar_decisao(
                id_aprovacao, usuario_aprovador, motivo
            )
            return jsonify({"sucesso": sucesso}), 200 if sucesso else 404
        except Exception as e:
            logger.exception(f"Erro ao aprovar: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/aprovacoes/<id_aprovacao>/rejeitar", methods=["POST"])
    def rejeitar_decisao(id_aprovacao):
        """Endpoint para rejeitar uma decisão pendente."""
        try:
            data = request.get_json()
            usuario_aprovador = data.get("usuario_aprovador", "admin")
            motivo = data.get("motivo", "")

            sucesso = governanca_manager["gestor_threshold"].rejeitar_decisao(
                id_aprovacao, usuario_aprovador, motivo
            )
            return jsonify({"sucesso": sucesso}), 200 if sucesso else 404
        except Exception as e:
            logger.exception(f"Erro ao rejeitar: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/assinaturas", methods=["GET"])
    def get_assinaturas():
        """Endpoint para obter decisões assinadas."""
        try:
            filtro_tipo = request.args.get("tipo")
            assinaturas = governanca_manager["gestor_assinaturas"].listar_assinaturas(
                filtro_tipo
            )
            return jsonify({"assinaturas": assinaturas, "total": len(assinaturas)}), 200
        except Exception as e:
            logger.exception(f"Erro ao obter assinaturas: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @auditoria_bp.route("/stream", methods=["GET"])
    def stream_events():
        """SSE stream dos eventos de auditoria (fallback por leitura de arquivo)."""

        def gen():
            last_ts = None
            while True:
                try:
                    path = governanca_manager["dashboard"].evolucao_path
                    if not os.path.exists(path):
                        time.sleep(1)
                        continue
                    with open(path, "r", encoding="utf-8") as f:
                        dados = json.load(f)
                    # ordena por timestamp
                    dados_sorted = sorted(dados, key=lambda x: x.get("timestamp", ""))
                    new = [
                        d
                        for d in dados_sorted
                        if (last_ts is None) or (d.get("timestamp") > last_ts)
                    ]
                    if new:
                        last_ts = new[-1].get("timestamp")
                        for e in new:
                            yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                    time.sleep(1)
                except Exception:
                    time.sleep(2)

        return Response(stream_with_context(gen()), mimetype="text/event-stream")

    app.register_blueprint(auditoria_bp)
