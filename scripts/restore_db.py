#!/usr/bin/env python3
"""CLI script to restore the database from a Koofr WebDAV backup.

Usage:
    python scripts/restore_db.py [--list] [--backup-name NAME] [--force] [--yes]

Options:
    --list          Print available backups and exit.
    --backup-name   Specific backup filename to restore (default: latest).
    --force         Required when APP_ENVIRONMENT=production.
    --yes           Skip the typed confirmation (unattended use).

A restore replaces the whole database. Unless --yes is given, the script names
the target database and the backup and asks for the database name to be typed.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.services.backup_service import (
    BackupError,
    list_backups,
    run_restore,
)


def _print_backups() -> None:
    backups = list_backups()
    if not backups:
        print("No backups found.", file=sys.stderr)
        return
    for name in backups:
        print(name)


def _confirm_restore(backup_name: str | None) -> None:
    """A restore wipes the schema: name the target and the source and require
    the database name to be typed, so a copied command line or a typo in the
    shell history cannot replace the wrong database."""
    database_url = get_settings().database_url
    url = make_url(database_url.get_secret_value() if database_url else "")
    database = url.database or ""
    host = url.host or "local socket"
    source = backup_name or "the latest production backup"
    print(
        f"This replaces the database '{database}' on {host} with {source}.",
        file=sys.stderr,
    )
    try:
        answer = input(f"Type the database name ({database}) to continue: ")
    except EOFError:
        answer = ""
    if not database or answer.strip() != database:
        print("Aborted.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore the DB from a Koofr WebDAV backup.",
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the typed confirmation (unattended use).",
    )
    args = parser.parse_args()

    try:
        if args.list:
            _print_backups()
            sys.exit(0)
        if not args.yes:
            _confirm_restore(args.backup_name)
        restored = run_restore(backup_name=args.backup_name, force=args.force)
        print(f"Restore complete. Backup: {restored}")
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
