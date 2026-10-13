"""Private storage for original tachograph files.

The specification requires that originals are preserved, hashed, and **not**
exposed through public URLs. This module is the only thing that writes them, and
it deliberately exposes no URL — only content-addressed filesystem paths. The API
layer has no endpoint that returns file bytes, which is what makes that guarantee
hold rather than merely being intended.

Layout::

    <storage_dir>/objects/<first two hex chars>/<sha256>.ddd

Content addressing means an identical file uploaded twice writes once, and the
name can never disagree with the contents. The directory is created with mode
0700 and each file with 0600, because these are driver personal data.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    size_bytes: int
    path: str
    #: True when the object already existed; the caller uses this for duplicate
    #: detection reporting.
    already_present: bool


class ObjectStore:
    """Content-addressed, private, append-only-ish storage for originals."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.objects_dir = os.path.join(self.root, "objects")

    # -- setup ------------------------------------------------------------
    def ensure_directories(self) -> None:
        os.makedirs(self.objects_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
            os.chmod(self.objects_dir, 0o700)
        except OSError:
            # A mounted volume may not permit chmod; not fatal, but the operator
            # should know that permissions are then whatever the mount gave us.
            pass

    # -- paths ------------------------------------------------------------
    @staticmethod
    def sha256_of(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def path_for(self, sha256: str) -> str:
        if len(sha256) != 64:
            raise ValueError("sha256 must be 64 hex characters")
        return os.path.join(self.objects_dir, sha256[:2], "%s.ddd" % sha256)

    def exists(self, sha256: str) -> bool:
        return os.path.exists(self.path_for(sha256))

    # -- writing ----------------------------------------------------------
    def put(self, data: bytes, sha256: Optional[str] = None) -> StoredObject:
        """Store ``data``, returning its content address.

        Writes to a temporary file and renames into place, so an interrupted write
        cannot leave a truncated object that later looks like a valid cache hit.
        """
        digest = sha256 or self.sha256_of(data)
        target = self.path_for(digest)

        # Verify when the caller supplied the digest: never trust a hash that was
        # not computed here.
        if sha256 is not None and self.sha256_of(data) != sha256:
            raise ValueError("supplied sha256 does not match the data")

        if os.path.exists(target):
            return StoredObject(
                sha256=digest,
                size_bytes=os.path.getsize(target),
                path=target,
                already_present=True,
            )

        directory = os.path.dirname(target)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        temporary = "%s.tmp.%d" % (target, os.getpid())
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        return StoredObject(
            sha256=digest, size_bytes=len(data), path=target, already_present=False
        )

    # -- reading ----------------------------------------------------------
    def read(self, sha256: str) -> bytes:
        with open(self.path_for(sha256), "rb") as handle:
            return handle.read()

    def verify(self, sha256: str) -> bool:
        """Re-hash a stored object and compare. Used by the integrity check."""
        path = self.path_for(sha256)
        if not os.path.exists(path):
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == sha256

    def iter_objects(self) -> Iterator[str]:
        for directory, _subdirs, filenames in os.walk(self.objects_dir):
            for filename in filenames:
                if filename.endswith(".ddd"):
                    yield os.path.join(directory, filename)
