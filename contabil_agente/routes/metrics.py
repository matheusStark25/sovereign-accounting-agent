"""Blueprint de métricas simples: conta downloads e uso de armazenamento.

Expondo `/metrics` que retorna JSON com:
- total_downloads: número total de entradas no audit log
- downloads_per_file: contagem por arquivo (top 20)
- downloads_last_24h: contagens nas últimas 24h
- storage: { disk_bytes, disk_files, s3_bytes (if available), s3_objects }
"""

from flask import Blueprint, jsonify, current_app
from collections import Counter
from datetime import datetime, timedelta
import os
import json
from typing import Dict, Any

metrics_bp = Blueprint("metrics_bp", __name__)


def _read_audit_log(path: str):
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    ts, ip, filename = parts[0], parts[1], parts[2]
                    out.append({"ts": ts, "ip": ip, "filename": filename})
    except Exception:
        return []
    return out


@metrics_bp.route("/metrics", methods=["GET"])
def metrics():
    root = os.path.dirname(os.path.dirname(__file__))
    # Audit log
    logs_dir = os.path.join(root, "logs")
    audit_log = os.path.join(logs_dir, "download_audit.log")
    entries = _read_audit_log(audit_log)

    total_downloads = len(entries)
    downloads_per_file = Counter(e["filename"] for e in entries)

    # last 24h
    now = datetime.utcnow()
    cutoff = now - timedelta(days=1)
    recent = 0
    for e in entries:
        try:
            t = datetime.fromisoformat(e["ts"].replace("Z", ""))
            if t >= cutoff:
                recent += 1
        except Exception:
            continue

    # Storage usage from manifest
    storage = {"disk_bytes": 0, "disk_files": 0, "s3_bytes": None, "s3_objects": None}
    try:
        from contabil_agente.services import pdf_store

        # load manifest
        manifest = {}
        try:
            # use internal loader if available
            manifest = pdf_store._load_manifest()
        except Exception:
            try:
                with open(pdf_store.MANIFEST_PATH, "r", encoding="utf-8") as mf:
                    manifest = json.load(mf)
            except Exception:
                manifest = {}

        for k, v in manifest.items():
            if v.get("storage") == "disk":
                size = v.get("size") or 0
                storage["disk_bytes"] += int(size)
                storage["disk_files"] += 1

        # If S3 configured, try to compute bucket usage (best-effort)
        try:
            s3_client, bucket = pdf_store._s3_client()
            if s3_client and bucket:
                # paginated listing
                total = 0
                count = 0
                kwargs = {"Bucket": bucket}
                resp = s3_client.list_objects_v2(**kwargs)
                while True:
                    contents = resp.get("Contents") or []
                    for obj in contents:
                        total += int(obj.get("Size", 0))
                        count += 1
                    if resp.get("IsTruncated"):
                        kwargs["ContinuationToken"] = resp.get("NextContinuationToken")
                        resp = s3_client.list_objects_v2(**kwargs)
                    else:
                        break
                storage["s3_bytes"] = total
                storage["s3_objects"] = count
        except Exception:
            # best-effort only
            pass
    except Exception:
        pass

    out: Dict[str, Any] = {
        "total_downloads": total_downloads,
        "downloads_last_24h": recent,
        "downloads_per_file_top": downloads_per_file.most_common(20),
        "storage": storage,
    }
    return jsonify(out)
