"""A lock file so the hourly and weekly runs never overlap."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path("jobscout.lock")
STALE_SECONDS = 2 * 3600


class LockBusy(Exception):
    """Another run holds the lock."""


def _create(path: Path) -> int:
    return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


@contextmanager
def file_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    try:
        fd = _create(path)
    except FileExistsError:
        if time.time() - path.stat().st_mtime < STALE_SECONDS:
            raise LockBusy(str(path)) from None
        path.unlink(missing_ok=True)  # left behind by a crashed run
        fd = _create(path)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
