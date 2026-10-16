"""
Sistema de Evolução e Self-Learning
Registra operações para aprendizado contínuo
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


class EvolutionManager:
    """Gerencia evolução e aprendizado do sistema"""

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "evolucao_sistema.json")
        self.lock = threading.Lock()

    def registrar(
        self,
        comando_usuario: str,
        intencao: str,
        status_sucesso: bool,
        tempo_processamento: float,
        tone: str = "neutro",
    ):
        """Registra operação para análise e evolução"""
        entrada = {
            "timestamp": datetime.now().isoformat(),
            "comando_usuario": comando_usuario,
            "intencao_detectada": intencao,
            "status_sucesso": status_sucesso,
            "tempo_processamento_seg": round(tempo_processamento, 3),
            "tone": tone,
        }

        with self.lock:
            try:
                if not os.path.exists(self.log_path):
                    with open(self.log_path, "w", encoding="utf-8") as f:
                        json.dump([entrada], f, ensure_ascii=False, indent=2)
                else:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        try:
                            dados = json.load(f)
                        except json.JSONDecodeError:
                            dados = []

                    dados.append(entrada)

                    with open(self.log_path, "w", encoding="utf-8") as f:
                        json.dump(dados, f, ensure_ascii=False, indent=2)

            except Exception:
                logger.exception("Falha ao registrar evolução do sistema")


class CalculationLogger:
    """Logger detalhado de cálculos"""

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

    def write(self, session_id: str, calculo: Dict[str, Any]) -> str:
        """
        Grava log detalhado de cálculo

        Args:
            session_id: ID da sessão
            calculo: Dicionário com detalhes do cálculo

        Returns:
            Caminho do arquivo gerado
        """
        try:
            filename = (
                f"calc_{session_id[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            )
            path = os.path.join(self.log_dir, filename)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(calculo, f, ensure_ascii=False, indent=2)

            return path

        except Exception:
            logger.exception("Falha ao gravar log de cálculo")
            return ""
