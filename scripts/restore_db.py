#!/usr/bin/env python3
"""CLI script to restore the SQLite database from a Koofr WebDAV backup.

Usage:
    python scripts/restore_db.py [--list] [--backup-name NAME] [--force]

Options:
    --list          Print available backups and exit.
    --backup-name   Specific backup filename to restore (default: latest).
    --force         Required when APP_ENVIRONMENT=production.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.backup_service import (
    BackupError,
    list_backups,
    run_restore,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore the SQLite DB from a Koofr WebDAV backup.",
    )
    parser.add_argument(
        "--backup-name",
        metavar="NAME",
        help="Backup filename to restore (default: latest).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required when APP_ENVIRONMENT=production.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backups and exit.",
    )
    args = parser.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found.", file=sys.stderr)
            sys.exit(0)
        for name in backups:
            print(name)
        sys.exit(0)

    try:
        restored = run_restore(backup_name=args.backup_name, force=args.force)
        print(f"Restore complete. Backup: {restored}")
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
