#!/usr/bin/env python3
"""One-time backfill: map the informal "(S)/(A)/(T)/(B)" surname suffix
convention to real UserPosition("voices") rows, for exactly the users
currently booked into ANY choirjobs position. Read-only on `users.surname`
-- never rewrites the name itself, only adds structured qualification
rows. Safe to re-run (idempotent: an existing UserPosition is reported,
never duplicated). Fully non-interactive -- no prompts; an unrecognized or
missing bracket tag is simply skipped and reported, never guessed.

Usage:
    python scripts/backfill_choir_voice_tags.py [--dry-run]

Options:
    --dry-run   Report what would be mapped, without writing anything.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session

# Registers every model so SQLAlchemy can resolve string-based
# relationship() arguments (e.g. User.roles -> "UserRole") regardless of
# which model is queried first, same 1:1 pattern as main.py.
import app.db.base  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.db.database import SessionLocal
from app.db.models.booking import Booking
from app.db.models.user import User
from app.db.models.voice import Voice
from app.services.user_position_service import (
    create_user_position,
    get_position_ids_for_user,
)

TAG_TO_VOICE_NAME = {"S": "Sopran", "A": "Alt", "T": "Tenor", "B": "Bass"}
TAG_PATTERN = re.compile(r"\(([^)]*)\)")


def run_backfill(db: Session, *, dry_run: bool) -> None:
    """Core logic, taking an already-constructed Session -- kept separate
    from main() so tests can inject the isolated per-test session instead
    of a real SessionLocal()."""
    voices = db.execute(select(Voice)).scalars().all()
    voice_id_by_name = {voice.name: voice.id for voice in voices}
    choirjob_user_ids = (
        db.execute(
            select(Booking.user_id)
            .where(Booking.position_type == "choirjobs")
            .distinct()
        )
        .scalars()
        .all()
    )
    users = (
        db.execute(select(User).where(User.id.in_(choirjob_user_ids))).scalars().all()
    )

    mapped = skipped = 0
    for user in sorted(users, key=lambda u: (u.surname, u.givenname)):
        label = f"{user.surname}, {user.givenname} (id={user.id})"
        match = TAG_PATTERN.search(user.surname)
        if not match:
            print(f"[skip] {label}: kein Klammer-Kürzel im Namen")
            skipped += 1
            continue

        tag = match.group(1)
        voice_name = TAG_TO_VOICE_NAME.get(tag)
        if voice_name is None:
            print(f"[skip] {label}: unbekanntes Kürzel {tag!r}")
            skipped += 1
            continue

        voice_id = voice_id_by_name[voice_name]
        if voice_id in get_position_ids_for_user(db, user.id)["voices"]:
            print(f"[skip] {label}: bereits vorhanden ({voice_name})")
            skipped += 1
            continue

        verb = "würde mappen" if dry_run else "mappe"
        print(f"[map]  {label}: {verb} -> {voice_name}")
        mapped += 1
        if not dry_run:
            create_user_position(
                db, user_id=user.id, position_type="voices", position_id=voice_id
            )

    print(f"\nFertig: {mapped} gemappt, {skipped} übersprungen.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill UserPosition(voices) from the (S)/(A)/(T)/(B) surname convention."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be mapped, without writing.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        run_backfill(db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
