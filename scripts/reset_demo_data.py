"""Explicit reset of local demo data. Never runs automatically.

Default is to ARCHIVE: the data directory is renamed to a unique sibling
`<name>-archive-<UTC timestamp with microseconds>-<random>` so history is kept. Deleting needs both
--confirm and --delete.

    python scripts/reset_demo_data.py --confirm            # archive ./data, start fresh
    python scripts/reset_demo_data.py --confirm --delete   # permanently delete ./data

Safety (R5-04). Before ANY change to the directory, its files, databases or WAL files, the script:
  1. resolves the target to its canonical real path (symlinks, `.` and `..` resolved);
  2. refuses the filesystem root, the home directory and its ancestors, the source checkout (anything
     containing .git, the repository itself or its ancestors, and any repository path other than ./data);
  3. requires the app's ownership marker (.adops-data-marker), and only recognised demo files inside:
     the two SQLite databases and their -wal/-shm/-journal files, the crash-drill marker, lock files,
     and nested directories that pass the same check;
  4. takes an EXCLUSIVE, non-blocking lock on the lock file next to the directory. A running backend
     holds a shared lock on the same file for its whole lifetime, so reset refuses while it runs.
Linux is tested. macOS (BSD flock) is untested. Windows is unsupported.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.datalock import MARKER, DataDirBusy, DataDirLock, canonical  # noqa: E402

DB_FILE = re.compile(r"^(adops|checkpoints)\.db(-wal|-shm|-journal)?$")
LOCK_FILE = re.compile(r"^\.[^/]+\.adops\.lock$")
OTHER_ALLOWED = {MARKER, ".crash_drill_fired"}


def _content_problems(d: Path, depth: int = 0) -> list[str]:
    problems = []
    if not (d / MARKER).is_file():
        return [f"{d}: no ownership marker {MARKER}"]
    for entry in d.iterdir():
        if entry.is_symlink():
            problems.append(f"{entry}: symlink")
        elif entry.is_dir():
            if depth >= 2:
                problems.append(f"{entry}: nested too deep")
            else:
                problems.extend(_content_problems(entry, depth + 1))
        elif not (DB_FILE.match(entry.name) or LOCK_FILE.match(entry.name) or entry.name in OTHER_ALLOWED):
            problems.append(f"{entry}: not a recognised demo data file")
    return problems


def validate_target(path: Path | str) -> str | None:
    """Return a refusal reason, or None if `path` is a recognised demo data directory. Read-only."""
    c = canonical(path)
    if c == Path(c.anchor):
        return "refusing the filesystem root"
    home = canonical(Path.home())
    if c == home or c in home.parents:
        return "refusing the home directory or one of its ancestors"
    repo = canonical(ROOT)
    if c == repo or c in repo.parents:
        return "refusing the source checkout or one of its ancestors"
    if repo in c.parents and not (c == repo / "data" or (repo / "data") in c.parents):
        return "refusing a path inside the source checkout other than ./data"
    if (c / ".git").exists():
        return "refusing a directory that looks like a source checkout (.git present)"
    if not c.is_dir():
        return "not a directory"
    problems = _content_problems(c)
    if problems:
        return "not a recognised demo data directory: " + "; ".join(problems[:5])
    return None


def _unique_archive(c: Path) -> Path:
    for _ in range(10):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = c.parent / f"{c.name}-archive-{stamp}-{uuid.uuid4().hex[:8]}"
        try:
            os.mkdir(dest)            # exclusive: fails if the name exists, so nothing is overwritten
        except FileExistsError:
            continue
        return dest
    raise RuntimeError("could not allocate a unique archive name")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true", help="required; without it nothing happens")
    ap.add_argument("--delete", action="store_true", help="delete instead of archiving")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args(argv)
    if not os.path.lexists(args.data_dir):
        print(f"nothing to reset: {args.data_dir} does not exist")
        return 0
    if not args.confirm:
        print(f"refusing: pass --confirm to reset {args.data_dir} (it will be archived, not deleted)")
        return 2
    reason = validate_target(args.data_dir)
    if reason:
        print(f"refusing: {reason}. Nothing was changed.")
        return 3
    c = canonical(args.data_dir)
    try:
        lock = DataDirLock(c, exclusive=True)
    except DataDirBusy as e:
        print(f"refusing: the backend appears to be running ({e}). Stop it first. Nothing was changed.")
        return 4
    try:
        reason = validate_target(c)   # re-check under the lock
        if reason:
            print(f"refusing: {reason}. Nothing was changed.")
            return 3
        if args.delete:
            shutil.rmtree(c)
            print(f"deleted {c}")
        else:
            dest = _unique_archive(c)
            os.rename(c, dest)        # replaces the empty placeholder atomically; never nests
            print(f"archived {c} -> {dest}")
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
