from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

try:
    import aioboto3
except Exception:  # aioboto3 optional
    aioboto3 = None


class StorageClient(ABC):
    """Abstract async storage interface."""

    @abstractmethod
    async def upload(self, key: str, data: bytes) -> str:
        raise NotImplementedError()

    @abstractmethod
    async def download(self, key: str) -> bytes:
        raise NotImplementedError()


class LocalStorage(StorageClient):
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, data: bytes) -> str:
        path = self.base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def download(self, key: str) -> bytes:
        path = self.base / key
        return path.read_bytes()


class S3Storage(StorageClient):
    def __init__(
        self,
        bucket: str,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        if aioboto3 is None:
            raise RuntimeError("aioboto3 required for S3Storage")
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key

    async def _session(self):
        return aioboto3.Session().client(
            "s3",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            endpoint_url=self.endpoint_url,
        )

    async def upload(
        self,
        key: str,
        data: bytes,
        server_side_encryption: Optional[str] = None,
        sse_kms_key_id: Optional[str] = None,
    ) -> str:
        async with await self._session() as client:
            put_kwargs = dict(Bucket=self.bucket, Key=key, Body=data)
            if server_side_encryption:
                put_kwargs["ServerSideEncryption"] = server_side_encryption
            if sse_kms_key_id:
                put_kwargs["SSEKMSKeyId"] = sse_kms_key_id
            await client.put_object(**put_kwargs)
        return f"s3://{self.bucket}/{key}"

    async def download(self, key: str) -> bytes:
        async with await self._session() as client:
            obj = await client.get_object(Bucket=self.bucket, Key=key)
            async with obj["Body"] as stream:
                return await stream.read()
