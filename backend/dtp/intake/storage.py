"""Object storage abstraction (SRS-003, SRS-005).
Stores original uploaded bytes by content SHA-256 in an immutable, tenant-partitioned path.
Local file-system adapter for dev/local execution, versioned S3/GCS contract interface for production.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

_ROOT = Path(__file__).resolve().parents[3]


class ObjectStore:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or (_ROOT / "data" / "objects")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, sha256: str) -> Path:
        prefix = sha256[:2]
        return self.base_dir / tenant_id / prefix / sha256

    def put(self, tenant_id: str, data: bytes) -> tuple[str, int]:
        """Store bytes under immutable content-addressed path. Returns (sha256, size_bytes)."""
        sha = hashlib.sha256(data).hexdigest()
        target = self._path(tenant_id, sha)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return sha, len(data)

    def get(self, tenant_id: str, sha256: str) -> bytes:
        p = self._path(tenant_id, sha256)
        if not p.exists():
            raise FileNotFoundError(f"Object {sha256} not found for tenant")
        return p.read_bytes()

    def exists(self, tenant_id: str, sha256: str) -> bool:
        return self._path(tenant_id, sha256).exists()


object_store = ObjectStore()
