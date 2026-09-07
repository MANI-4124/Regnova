from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentStorage(ABC):
    """
    Storage interface for document binaries (FR-04). A new top-level
    package, parallel to app/engine/ - a technical layer, not a
    bounded/domain module. See CLAUDE.md "Document storage and
    versioning".

    Content-addressed by design: `checksum` is both the identity and
    the storage key, so `put()` is naturally idempotent - the same
    bytes written twice land in the same location once. Dedup falls
    out of the interface shape rather than needing a separate registry
    table; DocumentVersionService still keeps its own `checksum` column
    for querying, but storage-level "don't write it twice" needs
    nothing beyond this.
    """

    @abstractmethod
    def put(self, checksum: str, content: bytes) -> None:
        """No-op if this checksum is already stored."""

    @abstractmethod
    def get(self, checksum: str) -> bytes:
        ...

    @abstractmethod
    def delete(self, checksum: str) -> None:
        """No-op if this checksum isn't stored."""

    @abstractmethod
    def exists(self, checksum: str) -> bool:
        ...


class LocalFilesystemStorage(DocumentStorage):
    """
    V1 storage backend - plain files on local disk, sharded by checksum
    prefix (root/ab/cd/abcd1234...) so a single directory never holds
    an unbounded number of entries. A future object-storage backend
    (S3, etc.) implements the exact same DocumentStorage shape -
    swapping backends is a settings change, not a service-layer
    rewrite. Deliberately not chosen as the only backend forever: see
    Settings.document_storage_backend.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, checksum: str) -> Path:
        return self.root / checksum[:2] / checksum[2:4] / checksum

    def put(self, checksum: str, content: bytes) -> None:
        path = self._path_for(checksum)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get(self, checksum: str) -> bytes:
        return self._path_for(checksum).read_bytes()

    def delete(self, checksum: str) -> None:
        path = self._path_for(checksum)
        if path.exists():
            path.unlink()

    def exists(self, checksum: str) -> bool:
        return self._path_for(checksum).exists()
