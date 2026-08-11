#!/usr/bin/env python3
"""CLI script to manually trigger a Koofr WebDAV database backup.

Usage:
    python scripts/backup_db.py [--list] [--cleanup] [--dry-run]

Options:
    --list      Print available Koofr backups and exit (no backup created).
    --cleanup   Also delete backups older than KOOFR_BACKUP_RETENTION_DAYS
                after the new backup succeeds (same cleanup the scheduled
                backup_koofr job runs; opt-in here so a manual backup never
                deletes other backups as a side effect unless requested).
    --dry-run   Only in combination with --cleanup: report which backups
                would be deleted without deleting them.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.backup_service import (
    BackupError,
    cleanup_old_backups,
    list_backups,
    run_backup,
)


def _print_backup_list() -> None:
    backups = list_backups()
    if not backups:
        print("No backups found.", file=sys.stderr)
        return
    for name in backups:
        print(name)


def _run_cleanup(*, dry_run: bool) -> None:
    affected = cleanup_old_backups(dry_run=dry_run)
    if not affected:
        print("No expired backups to clean up.")
        return
    verb = "Would clean up" if dry_run else "Cleaned up"
    print(f"{verb} {len(affected)} expired backup(s):")
    for name in affected:
        print(f"  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually trigger a Koofr WebDAV DB backup.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backups and exit, without creating one.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Also delete backups older than KOOFR_BACKUP_RETENTION_DAYS afterward.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --cleanup: report what would be deleted, without deleting it.",
    )
    args = parser.parse_args()

    if args.list:
        _print_backup_list()
        sys.exit(0)

    try:
        backup_name = run_backup()
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Backup complete: {backup_name}")

    if args.cleanup:
        _run_cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
