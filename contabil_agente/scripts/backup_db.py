"""
Script de Backup Automático de Bancos de Dados
"""

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backup_database(db_path: str, backup_dir: str = "backups") -> str:
    """
    Faz backup de um banco de dados SQLite
    Retorna o caminho do backup criado
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database não encontrado: {db_path}")

    # Criar diretório de backup
    backup_path = Path(backup_dir)
    backup_path.mkdir(exist_ok=True, parents=True)

    # Nome do backup com timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_name = Path(db_path).stem
    backup_file = backup_path / f"{db_name}_{timestamp}.db"

    # Copiar arquivo
    logger.info(f"Criando backup: {db_path} -> {backup_file}")
    shutil.copy2(db_path, backup_file)

    # Verificar tamanho
    original_size = os.path.getsize(db_path)
    backup_size = os.path.getsize(backup_file)

    if original_size != backup_size:
        raise Exception(
            f"Tamanhos diferentes! Original: {original_size}, Backup: {backup_size}"
        )

    logger.info(f"✅ Backup criado com sucesso: {backup_file} ({backup_size} bytes)")

    return str(backup_file)


def backup_all_empresas(empresas_db_dir: str = "db", backup_dir: str = "backups"):
    """Faz backup de todos os bancos de empresas"""
    db_path = Path(empresas_db_dir)

    if not db_path.exists():
        logger.warning(f"Diretório de DBs não encontrado: {empresas_db_dir}")
        return

    # Encontrar todos os .db
    db_files = list(db_path.glob("*.db"))

    if not db_files:
        logger.warning("Nenhum banco de dados encontrado")
        return

    logger.info(f"Encontrados {len(db_files)} bancos para backup")

    backups_created = []
    for db_file in db_files:
        try:
            backup_path = backup_database(str(db_file), backup_dir)
            backups_created.append(backup_path)
        except Exception as e:
            logger.error(f"Erro ao fazer backup de {db_file}: {e}")

    logger.info(f"✅ Total de backups criados: {len(backups_created)}")

    return backups_created


def cleanup_old_backups(backup_dir: str = "backups", keep_days: int = 30):
    """Remove backups mais antigos que N dias"""
    backup_path = Path(backup_dir)

    if not backup_path.exists():
        return

    cutoff_time = time.time() - (keep_days * 24 * 3600)
    removed_count = 0

    for backup_file in backup_path.glob("*.db"):
        if backup_file.stat().st_mtime < cutoff_time:
            logger.info(f"Removendo backup antigo: {backup_file}")
            backup_file.unlink()
            removed_count += 1

    if removed_count > 0:
        logger.info(f"✅ Removidos {removed_count} backups antigos (>{keep_days} dias)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backup de bancos de dados")
    parser.add_argument("--db-dir", default="db", help="Diretório dos bancos")
    parser.add_argument("--backup-dir", default="backups", help="Diretório de backup")
    parser.add_argument("--cleanup", action="store_true", help="Limpar backups antigos")
    parser.add_argument(
        "--keep-days", type=int, default=30, help="Dias para manter backups"
    )

    args = parser.parse_args()

    # Fazer backup
    backup_all_empresas(args.db_dir, args.backup_dir)

    # Limpar backups antigos se solicitado
    if args.cleanup:
        cleanup_old_backups(args.backup_dir, args.keep_days)
