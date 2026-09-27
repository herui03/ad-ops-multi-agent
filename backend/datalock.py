"""Lifetime lock and ownership marker for a demo data directory (POSIX flock).

* The lock file sits NEXT TO the data directory (`<parent>/.<name>.adops.lock`), keyed by the canonical
  real path, so moving the data directory never moves the lock, and aliases (symlinks, `..`, `.`) of the
  same directory map to the same lock.
* The backend holds a SHARED lock for as long as a WorkflowRunner is open. The reset script needs an
  EXCLUSIVE lock and takes it non-blocking before touching anything, so it refuses while a server runs;
  a server refuses to start while a reset holds the exclusive lock.
* `.adops-data-marker` marks a directory as created by this app; reset only accepts marked directories.

Tested on Linux. flock is also available on macOS but that platform has not been tested here; Windows
is not supported (no fcntl).
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

MARKER = ".adops-data-marker"
MARKER_CONTENT = {"app": "ad-ops-multi-agent", "kind": "demo-data",
                  "note": "Created by the app. scripts/reset_demo_data.py only resets directories with this marker."}


class DataDirBusy(RuntimeError):
    pass


def canonical(path: Path | str) -> Path:
    return Path(os.path.realpath(os.fspath(path)))


def lock_path(data_dir: Path | str) -> Path:
    c = canonical(data_dir)
    return c.parent / f".{c.name}.adops.lock"


class DataDirLock:
    def __init__(self, data_dir: Path | str, *, exclusive: bool):
        self.path = lock_path(data_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as e:
            os.close(self._fd)
            self._fd = None
            who = "a running server holds it" if exclusive else "a reset is in progress"
            raise DataDirBusy(f"data directory {canonical(data_dir)} is locked ({who}); lock file {self.path}") from e

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


def ensure_marker(data_dir: Path) -> None:
    m = Path(data_dir) / MARKER
    if not m.exists():
        m.write_text(json.dumps(MARKER_CONTENT, indent=2) + "\n")
