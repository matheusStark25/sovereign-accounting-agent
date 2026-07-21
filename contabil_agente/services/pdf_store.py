import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

try:
    import portalocker
except Exception:
    portalocker = None


ROOT = Path(__file__).resolve().parents[1]
STATIC_DOWNLOADS = ROOT / "static" / "downloads"
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "pdf_manifest.json"
LOCK_PATH = DATA_DIR / "pdf_manifest.lock"


def _ensure_dirs() -> None:
    STATIC_DOWNLOADS.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _acquire_lock(timeout: float = 5.0) -> bool:
    """Acquire a manifest lock.

    Uses `portalocker` if available for robust cross-platform locking. Falls
    back to a simple lockfile create/poll strategy when portalocker is not
    installed.
    Returns True if lock was acquired, False on timeout.
    """
    _ensure_dirs()
    if portalocker:
        try:
            # portalocker.Lock will create the file if needed and block until
            # the lock is available or timeout.
            lock = portalocker.Lock(str(LOCK_PATH), mode="w", timeout=timeout)
            lock.acquire()
            # store the acquired lock object globally so release can close it
            setattr(_acquire_lock, "_portalocker_lock", lock)
            return True
        except Exception:
            return False

    # Fallback naive lockfile approach
    start = time.time()
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()}\n{time.time()}".encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            if time.time() - start > timeout:
                return False
            time.sleep(0.05)
        except Exception:
            return False


def _release_lock() -> None:
    try:
        # If portalocker was used, release that lock object
        lock = getattr(_acquire_lock, "_portalocker_lock", None)
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass
            try:
                lock.close()
            except Exception:
                pass
            try:
                delattr(_acquire_lock, "_portalocker_lock")
            except Exception:
                pass

        # remove the sentinel lock file if present (fallback case)
        if LOCK_PATH.exists():
            try:
                LOCK_PATH.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _load_manifest() -> dict:
    _ensure_dirs()
    # Acquire lock for read to avoid partial writes
    if not MANIFEST_PATH.exists():
        return {}
    locked = _acquire_lock(timeout=2.0)
    if not locked:
        # Failed to acquire lock within timeout; return empty to avoid blocking
        return {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
            normalized = {}
            for name, entry in m.items():
                try:
                    normalized[name] = _normalize_entry(name, entry)
                except Exception:
                    normalized[name] = entry
            return normalized
    except Exception:
        return {}
    finally:
        _release_lock()


def _save_manifest(m: dict) -> None:
    _ensure_dirs()
    # Acquire lock to ensure no concurrent writers
    locked = _acquire_lock(timeout=5.0)
    if not locked:
        raise RuntimeError("Could not acquire manifest lock to save manifest")
    try:
        tmp = MANIFEST_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        tmp.replace(MANIFEST_PATH)
    finally:
        _release_lock()


def _normalize_entry(name: str, entry: dict) -> dict:
    """Ensure manifest entry contains standard keys: session_id, filename,
    storage, path, size, timestamp, mime, owner, ttl_days, expires_at.
    """
    out = dict(entry)
    try:
        if "filename" not in out:
            out["filename"] = name
        # storage inference
        if "storage" not in out:
            if out.get("path") and str(out.get("path")).startswith("static"):
                out["storage"] = "disk"
            else:
                out["storage"] = out.get("storage", "disk")
        # size
        if "size" not in out:
            try:
                p = ROOT / out.get("path", "")
                if p.exists():
                    out["size"] = p.stat().st_size
            except Exception:
                out["size"] = out.get("size")
        # timestamps
        if "timestamp" not in out:
            out["timestamp"] = datetime.utcnow().isoformat() + "Z"
        # mime
        if "mime" not in out:
            import mimetypes

            mime, _ = mimetypes.guess_type(out.get("filename", name))
            out["mime"] = mime or "application/pdf"
        # owner
        if "owner" not in out:
            out["owner"] = out.get("session_id") or "unknown"
        # ttl and expires
        if "ttl_days" not in out:
            out["ttl_days"] = 30
        try:
            from dateutil import parser as _p

            ts = _p.isoparse(out["timestamp"])
            expires = ts + timedelta(days=int(out["ttl_days"]))
            out["expires_at"] = expires.isoformat() + "Z"
        except Exception:
            try:
                from datetime import datetime, timedelta

                ts = datetime.utcnow()
                expires = ts + timedelta(days=int(out.get("ttl_days", 30)))
                out["expires_at"] = expires.isoformat() + "Z"
            except Exception:
                out["expires_at"] = None
    except Exception:
        pass
    return out


def _s3_client():
    """Return a boto3 S3 client if configuration present, else None."""
    endpoint = os.getenv("MINIO_ENDPOINT") or os.getenv("S3_ENDPOINT")
    access = os.getenv("MINIO_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("MINIO_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("S3_REGION") or os.getenv("AWS_REGION")
    bucket = (
        os.getenv("S3_BUCKET")
        or os.getenv("AWS_S3_BUCKET")
        or os.getenv("S3_BUCKET_NAME")
    )

    if not boto3 or not bucket:
        return None, None

    session_kwargs = {}
    client_kwargs = {}
    if access and secret:
        session_kwargs["aws_access_key_id"] = access
        session_kwargs["aws_secret_access_key"] = secret
    if region:
        session_kwargs["region_name"] = region
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint

    try:
        sess = boto3.session.Session(**session_kwargs)
        s3 = sess.client("s3", **client_kwargs)
        return s3, bucket
    except Exception:
        return None, None


def _upload_to_s3(src: Path, key: Optional[str] = None) -> str:
    s3, bucket = _s3_client()
    if not s3:
        raise RuntimeError("S3 client not configured or boto3 not installed")
    if key is None:
        key = src.name
    try:
        s3.upload_file(str(src), bucket, key)
    except (BotoCoreError, ClientError) as e:
        raise
    return key


def _generate_presigned_url(key: str, expires: int = 3600) -> Optional[str]:
    s3, bucket = _s3_client()
    if not s3:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )
    except Exception:
        return None


def register_pdf(src_path: str, session_id: Optional[str] = None) -> str:
    """Persist a PDF and register metadata.

    If S3/MinIO is configured (env vars), upload the file and record storage type 's3'.
    Otherwise move file to `static/downloads` and record storage type 'disk'.

    Returns a storage identifier (filename for disk, object key for s3).
    """
    _ensure_dirs()
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)

    # Prefer S3 if configured
    s3_client, bucket = _s3_client()
    manifest = _load_manifest()

    if s3_client and bucket:
        # Upload to S3 and remove local file
        key = src.name.replace(" ", "_")
        # avoid collisions by prefixing timestamp if key exists
        if key in manifest and manifest.get(key, {}).get("storage") == "s3":
            base = Path(key).stem
            suffix = Path(key).suffix
            key = f"{base}_{int(time.time())}{suffix}"
        _upload_to_s3(src, key=key)
        try:
            src.unlink()
        except Exception:
            pass

        manifest[key] = {
            "session_id": session_id,
            "filename": key,
            "storage": "s3",
            "bucket": bucket,
            "key": key,
            "size": None,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        _save_manifest(manifest)
        return key

    # Fallback: move to local static downloads
    dest_name = src.name.replace(" ", "_")
    dest = STATIC_DOWNLOADS / dest_name
    # If dest exists, append timestamp
    if dest.exists():
        base = dest.stem
        suffix = dest.suffix
        dest = STATIC_DOWNLOADS / f"{base}_{int(time.time())}{suffix}"

    shutil.move(str(src), str(dest))
    # Compose normalized manifest entry
    from datetime import datetime, timedelta
    import mimetypes

    mime, _ = mimetypes.guess_type(dest.name)
    ttl = int(os.getenv("PDF_TTL_DAYS", "30"))
    ts = datetime.utcnow().isoformat() + "Z"
    try:
        expires = (datetime.utcnow() + timedelta(days=ttl)).isoformat() + "Z"
    except Exception:
        expires = None

    manifest[dest.name] = {
        "session_id": session_id,
        "filename": dest.name,
        "storage": "disk",
        "path": str(dest.relative_to(ROOT)),
        "size": dest.stat().st_size,
        "timestamp": ts,
        "mime": mime or "application/pdf",
        "owner": session_id or "unknown",
        "ttl_days": ttl,
        "expires_at": expires,
    }
    _save_manifest(manifest)
    return dest.name


def get_metadata(filename: str) -> Optional[dict]:
    m = _load_manifest()
    return m.get(filename)


def get_download_url(filename: str, presign_seconds: int = 3600) -> Optional[str]:
    """Return a URL for downloading the persisted file.

    For S3 objects returns a presigned URL (best-effort). For disk files returns
    a stable path under `/static/downloads/<filename>` (relative path string).
    """
    m = _load_manifest()
    entry = m.get(filename)
    if not entry:
        return None
    if entry.get("storage") == "s3":
        url = _generate_presigned_url(entry.get("key"), expires=presign_seconds)
        return url
    # disk
    return f"/static/downloads/{entry.get('filename')}"


def remove_metadata(filename: str) -> None:
    m = _load_manifest()
    if filename in m:
        del m[filename]
        _save_manifest(m)
