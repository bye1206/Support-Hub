"""Local-disk file storage for message attachments (owner request 2026-11-19).

Files are stored under `files_dir` (config) keyed by a random server-side
key; the user-visible file name lives in the DB only. The storage is
deliberately dumb: open/save/read/delete — MinIO can replace it later
without touching callers (same four operations).
"""

import asyncio
import uuid
from pathlib import Path

from app.config import get_settings

_MAX_KEY_LENGTH = 64


class FileStorageError(Exception):
    """The file could not be stored or read."""


class LocalFileStorage:
    """Blocking disk IO wrapped in a worker thread (async entry points)."""

    def __init__(self, files_dir: str | None = None) -> None:
        self._files_dir = Path(files_dir or get_settings().files_dir)

    def _path(self, key: str) -> Path:
        if not key or len(key) > _MAX_KEY_LENGTH or "/" in key or "\\" in key:
            raise FileStorageError("Bad storage key")
        return self._files_dir / key

    async def save(self, content: bytes) -> str:
        """Write bytes under a fresh random key; returns the key."""
        key = uuid.uuid4().hex
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(_write)
        return key

    async def open(self, key: str) -> bytes:
        def _read() -> bytes:
            return self._path(key).read_bytes()

        try:
            return await asyncio.to_thread(_read)
        except OSError as exc:
            raise FileStorageError(f"File missing: {type(exc).__name__}") from exc

    async def delete(self, key: str) -> None:
        def _unlink() -> None:
            self._path(key).unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)
