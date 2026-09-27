"""Explicit reset of local demo data. Never runs automatically.

Default is to ARCHIVE: ./data is moved to ./data-archive-<UTC timestamp>/ so history is kept.
Deleting needs both --confirm and --delete. Stop the server first.

    python scripts/reset_demo_data.py --confirm            # archive, start fresh
    python scripts/reset_demo_data.py --confirm --delete   # permanently delete ./data
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true", help="required; without it nothing happens")
    ap.add_argument("--delete", action="store_true", help="delete instead of archiving")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()
    data = Path(args.data_dir)
    if not data.exists():
        print(f"nothing to reset: {data} does not exist")
        return 0
    if not args.confirm:
        print(f"refusing: pass --confirm to reset {data} (it will be archived, not deleted)")
        return 2
    if args.delete:
        shutil.rmtree(data)
        print(f"deleted {data}")
    else:
        dest = data.parent / f"data-archive-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        shutil.move(str(data), str(dest))
        print(f"archived {data} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
