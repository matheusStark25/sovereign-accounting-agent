import os
import threading
import hashlib
import uuid
import json
from pathlib import Path

try:
    # Load optional dependency without triggering static import errors in linters
    import importlib

    _magic = importlib.import_module("magic")
except Exception:
    _magic = None


def _detect_mime(file_path: Path) -> str:
    """Detect mime type using python-magic when available, else fallback to mimetypes.guess_type."""
    if _magic is not None:
        try:
            return _magic.from_file(str(file_path), mime=True)
        except Exception:
            pass
    import mimetypes

    mime, _ = mimetypes.guess_type(str(file_path))
    return mime or "application/octet-stream"


class IngestionService:
    def __init__(
        self,
        upload_folder: str,
        chunk_size: int = 65536,
        max_content_length: int = 16 * 1024 * 1024,
    ):
        self.upload_folder = Path(upload_folder)
        self.chunk_size = chunk_size
        self.max_content_length = max_content_length
        self.locks = {}
        self.locks_lock = threading.Lock()
        self.upload_folder.mkdir(exist_ok=True, parents=True)
        os.chmod(self.upload_folder, 0o750)

    def _get_lock(self, file_hash: str):
        with self.locks_lock:
            if file_hash not in self.locks:
                self.locks[file_hash] = threading.Lock()
            return self.locks[file_hash]

    def _deep_validate(self, file_path: Path, mime: str):
        # Only basic structure validation for demo: real impl should use pandas, openpyxl, etc.
        if mime == "application/json":
            with open(file_path, "r", encoding="utf-8") as f:
                json.load(f)
        elif mime in (
            "text/csv",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            import pandas as pd

            (
                pd.read_csv(file_path, nrows=1)
                if mime == "text/csv"
                else pd.read_excel(file_path, nrows=1)
            )
        # else: skip for other types

    def save(
        self,
        file_stream,
        filename: str,
        empresa_id: str,
        user_id: str,
        client_ip: str,
        user_agent: str,
    ) -> dict:
        transaction_id = str(uuid.uuid4())
        tmp_path = self.upload_folder / f".{filename}.{transaction_id}.tmp"
        sha256 = hashlib.sha256()
        size = 0
        try:
            # INÍCIO: Validação bruta de JSON antes de qualquer checagem de MIME
            import logging

            logger = logging.getLogger(__name__)
            file_stream.seek(0)
            try:
                content = file_stream.read().decode("utf-8")
                json.loads(content)
                logger.info("JSON VALIDADO MANUALMENTE - FORÇANDO ACEITAÇÃO")
                is_forced_json = True
            except Exception as e:
                logger.error(f"FALHA NA VALIDAÇÃO BRUTA: {str(e)}")
                is_forced_json = False
            file_stream.seek(0)

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = file_stream.read(self.chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
                    size += len(chunk)
                    if size > self.max_content_length:
                        raise ValueError("FILE_TOO_LARGE")
            os.chmod(tmp_path, 0o640)
            if size == 0:
                tmp_path.unlink(missing_ok=True)
                return {"error": "EMPTY_FILE", "code": "EMPTY_FILE"}
            # MIME validation
            mime = _detect_mime(tmp_path)
            # Se validou como JSON manualmente, força o MIME
            if is_forced_json:
                mime = "application/json"
            # Elite Duplo Fator: se for text/plain OU octet-stream e extensão .json, tenta validar JSON (mantido para fallback)
            if (
                not is_forced_json
                and mime in ("application/octet-stream", "text/plain")
                and tmp_path.suffix.lower() == ".json"
            ):
                try:
                    with open(tmp_path, "r", encoding="utf-8") as f:
                        f.seek(0)
                        try:
                            json.load(f)
                        except Exception as e:
                            logger.error(f"FALHA CRÍTICA NO JSON: {str(e)}")
                            tmp_path.unlink(missing_ok=True)
                            return {
                                "error": "JSON_MALFORMADO",
                                "detalhe": str(e),
                                "code": "INVALID_JSON",
                            }, 400
                    mime = "application/json"
                except Exception as e:
                    logger.error(f"Erro ao validar JSON no duplo fator: {e}")
                    tmp_path.unlink(missing_ok=True)
                    return {"error": f"INVALID_MIME: {mime}", "code": "INVALID_MIME"}
            if mime not in (
                "application/json",
                "text/csv",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ):
                tmp_path.unlink(missing_ok=True)
                return {"error": f"INVALID_MIME: {mime}", "code": "INVALID_MIME"}
            try:
                self._deep_validate(tmp_path, mime)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                return {"error": "INVALID_STRUCTURE", "code": "INVALID_STRUCTURE"}
            file_hash = sha256.hexdigest()
            lock = self._get_lock(file_hash + empresa_id)
            with lock:
                # Check for duplicate (idempotency)
                for f in self.upload_folder.glob(f"*_{empresa_id}_*.uploaded"):
                    if f.stem.endswith(file_hash):
                        tmp_path.unlink(missing_ok=True)
                        return {"error": "DUPLICATE_FILE", "code": "DUPLICATE_FILE"}
                # Atomic move
                safe_name = f"{filename}_{empresa_id}_{file_hash}.uploaded"
                dest = self.upload_folder / safe_name
                os.replace(tmp_path, dest)
                os.chmod(dest, 0o640)
            log = {
                "transaction_id": transaction_id,
                "user_id": user_id,
                "empresa_id": empresa_id,
                "file_hash": file_hash,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "status": "success",
            }
            print(json.dumps(log))
            return {"status": "success", "file_hash": file_hash, "filename": safe_name}
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            log = {
                "transaction_id": transaction_id,
                "user_id": user_id,
                "empresa_id": empresa_id,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "status": "error",
                "error": str(e),
            }
            print(json.dumps(log))
            return {"error": str(e), "code": "INTERNAL_ERROR"}
