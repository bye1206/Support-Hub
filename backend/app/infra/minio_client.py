"""MinIO client wrapper.

minio-py is synchronous; calls that can touch the network run in a worker
thread so the event loop is never blocked.
"""

import anyio
from minio import Minio


class MinioClient:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket

    async def health_check(self) -> None:
        """Raise if MinIO is unreachable or the configured bucket is missing."""
        exists: bool = await anyio.to_thread.run_sync(
            self._client.bucket_exists, self._bucket
        )
        if not exists:
            raise RuntimeError(f"bucket '{self._bucket}' does not exist")

    async def close(self) -> None:
        """No explicit close API in minio-py; HTTP pool is released with the client."""
        return None
