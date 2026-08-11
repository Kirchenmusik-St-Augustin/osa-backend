"""SQLite -> Koofr WebDAV backup/restore -- Phase 1 (SQLite) equivalent of
Legacy's OsaScheduleBackupProdDB.php Artisan command.

Produces filenames byte-for-byte compatible with
osa-einteilung.hochamt.at/tools/restore-koofr-backup.sh (same
"osa_database_backup_{Y-m-d_H-i-s}.tar.gz" naming, same Koofr path) --
that script keeps working unmodified against backups this module creates.

Uses raw WebDAV HTTP verbs via `requests` (already a pinned dependency)
instead of shelling out to rclone (what the existing restore script does)
or adding a dedicated WebDAV client library -- no new dependency, no
subprocess/shell-escaping surface.

Known, deliberately NOT replicated Legacy bug: Legacy's own
cleanupOldBackups() passes the WebDAV-absolute paths returned by PROPFIND
straight into a Laravel Storage disk whose configured `path` is itself a
root prefix -- an absolute path handed to that disk produces a
double-prefixed, nonexistent target, so the delete silently no-ops and old
backups pile up on Koofr. This module never reuses a raw path from a
listing response: `_parse_backup_filenames()` extracts only the basename,
and every delete/download URL is rebuilt fresh from
koofr_base_uri + koofr_backup_path + basename via `_koofr_url()`.
"""

import logging
import re
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import requests
from sqlalchemy.engine import make_url

from app.core.config import get_settings, require_setting

logger = logging.getLogger(__name__)

_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
_FILENAME_PATTERN = re.compile(
    r"^osa_database_backup_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.tar\.gz$"
)
_DAV_HREF_TAG = "{DAV:}href"


class BackupError(Exception):
    """Raised for any backup/restore failure -- the one exception type
    callers (scripts/backup_db.py, scripts/restore_db.py,
    app.services.backup_jobs) ever need to catch."""


def _sqlite_path() -> Path:
    """Extract the DB file path from DATABASE_URL. Backup/restore only
    ever run against SQLite in Phase 1 -- Phase 2 adds a parallel
    pg_dump/pg_restore-based path once Postgres lands (CLAUDE.md
    section 3)."""
    database_url = require_setting(get_settings().database_url, "DATABASE_URL")
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        msg = f"Backup/restore requires a SQLite DATABASE_URL, got: {database_url}"
        raise BackupError(msg)
    return Path(url.database)


def _koofr_auth() -> tuple[str, str]:
    settings = get_settings()
    try:
        return (
            require_setting(settings.koofr_user, "KOOFR_USER"),
            require_setting(settings.koofr_password, "KOOFR_PASSWORD"),
        )
    except RuntimeError as exc:
        # Normalizes require_setting()'s RuntimeError into BackupError so
        # every failure mode this module can produce is a single type.
        raise BackupError(str(exc)) from exc


def _koofr_url(filename: str = "") -> str:
    settings = get_settings()
    base = settings.koofr_base_uri.rstrip("/")
    path = settings.koofr_backup_path.strip("/")
    return f"{base}/{path}/{filename}" if filename else f"{base}/{path}/"


def _backup_sqlite_file(source_path: Path, dest_path: Path) -> None:
    """Consistent online snapshot via sqlite3's own C-level backup API
    (Connection.backup()) -- functionally identical to Legacy's
    `sqlite3 <db> ".backup <copy>"` CLI call, but native Python: no
    subprocess, no shell-escaping, no dependency on the sqlite3 CLI binary
    being present in the prod image."""
    source_conn = sqlite3.connect(source_path)
    try:
        dest_conn = sqlite3.connect(dest_path)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def run_backup() -> str:
    """Create a consistent SQLite snapshot, tar.gz it, upload to Koofr.

    Returns the uploaded archive's filename. Raises BackupError on any
    failure -- nothing is left behind on Koofr on failure, the upload is
    the last step.
    """
    source_path = _sqlite_path()
    timestamp = datetime.now(UTC).strftime(_TIMESTAMP_FORMAT)
    archive_name = f"osa_database_backup_{timestamp}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="osa-backup-") as tmp_dir:
        tmp_db_copy = Path(tmp_dir) / source_path.name
        tmp_archive = Path(tmp_dir) / archive_name

        logger.info("Creating consistent SQLite snapshot: %s", archive_name)
        _backup_sqlite_file(source_path, tmp_db_copy)

        with tarfile.open(tmp_archive, "w:gz") as tar:
            tar.add(tmp_db_copy, arcname=source_path.name)

        logger.info("Uploading backup to Koofr: %s", archive_name)
        _upload_to_koofr(archive_name, tmp_archive.read_bytes())

    logger.info("Backup complete: %s", archive_name)
    return archive_name


def _upload_to_koofr(filename: str, data: bytes) -> None:
    user, password = _koofr_auth()
    try:
        response = requests.put(
            _koofr_url(filename), data=data, auth=(user, password), timeout=120
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"Koofr upload failed for {filename}: {exc}"
        raise BackupError(msg) from exc


def list_backups() -> list[str]:
    """Sorted (oldest-first, filenames are timestamp-sortable) backup
    filenames currently on Koofr, via WebDAV PROPFIND (Depth 1)."""
    user, password = _koofr_auth()
    propfind_body = (
        '<?xml version="1.0"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>'
    )
    try:
        response = requests.request(
            "PROPFIND",
            _koofr_url(),
            data=propfind_body,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            auth=(user, password),
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"Koofr directory listing failed: {exc}"
        raise BackupError(msg) from exc
    return sorted(_parse_backup_filenames(response.text))


def _parse_backup_filenames(propfind_xml: str) -> list[str]:
    """Extract backup basenames from a WebDAV PROPFIND response body.

    Trusted input: Koofr is our own authenticated cloud-storage account,
    not attacker-controlled data -- xml.etree's documented XXE risk applies
    to untrusted/third-party XML, not a response from a service we
    authenticate to with our own credentials.

    Deliberately extracts ONLY the basename from each href, regardless of
    whether Koofr returns absolute or relative paths -- see this module's
    docstring for the Legacy bug this sidesteps.
    """
    root = ElementTree.fromstring(propfind_xml)  # noqa: S314 -- trusted source, see docstring
    names: list[str] = []
    for href in root.iter(_DAV_HREF_TAG):
        if href.text is None:
            continue
        name = href.text.rstrip("/").rsplit("/", 1)[-1]
        if _FILENAME_PATTERN.match(name):
            names.append(name)
    return names


def _parse_backup_timestamp(name: str) -> datetime | None:
    match = _FILENAME_PATTERN.match(name)
    if match is None:
        return None
    return datetime.strptime(match.group(1), _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def cleanup_old_backups(*, dry_run: bool = False) -> list[str]:
    """Delete Koofr backups older than koofr_backup_retention_days
    (default 28 = Legacy's hardcoded 4 weeks).

    Returns the filenames that were deleted (or, if dry_run=True, that
    WOULD be deleted -- nothing is actually removed in that case). Names
    that don't match the expected pattern are never touched.
    """
    retention_days = get_settings().koofr_backup_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    affected: list[str] = []
    for name in list_backups():
        backup_date = _parse_backup_timestamp(name)
        if backup_date is None or backup_date >= cutoff:
            continue
        if not dry_run:
            _delete_from_koofr(name)
        affected.append(name)
        logger.info(
            "%s expired Koofr backup (older than %dd): %s",
            "Would delete" if dry_run else "Deleted",
            retention_days,
            name,
        )
    return affected


def _delete_from_koofr(filename: str) -> None:
    user, password = _koofr_auth()
    try:
        response = requests.delete(
            _koofr_url(filename), auth=(user, password), timeout=30
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"Koofr delete failed for {filename}: {exc}"
        raise BackupError(msg) from exc


def run_restore(*, backup_name: str | None = None, force: bool = False) -> str:
    """Download a Koofr backup and atomically replace the local SQLite file.

    Extracts into a temp directory INSIDE the target file's own parent
    directory (not the system temp dir) so the final swap is a same-
    filesystem os.replace() -- a real atomic rename, not just a copy that
    could leave a half-written file behind on a crash.

    Requires force=True when APP_ENVIRONMENT=production -- a restore
    overwrites the live database.
    """
    if get_settings().app_environment == "production" and not force:
        msg = (
            "Restore in production requires explicit force=True. "
            "This operation is destructive."
        )
        raise BackupError(msg)

    if backup_name is None:
        available = list_backups()
        if not available:
            msg = "No backups found on Koofr."
            raise BackupError(msg)
        backup_name = available[-1]
        logger.info("Auto-selected latest backup: %s", backup_name)
    elif not _FILENAME_PATTERN.match(backup_name):
        msg = f"'{backup_name}' is not a valid backup filename."
        raise BackupError(msg)

    target_path = _sqlite_path()
    user, password = _koofr_auth()
    try:
        response = requests.get(
            _koofr_url(backup_name), auth=(user, password), timeout=120
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"Koofr download failed for {backup_name}: {exc}"
        raise BackupError(msg) from exc

    with tempfile.TemporaryDirectory(
        prefix=".osa-restore-", dir=target_path.parent
    ) as tmp_dir:
        archive_path = Path(tmp_dir) / backup_name
        archive_path.write_bytes(response.content)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tmp_dir, filter="data")
        extracted = Path(tmp_dir) / target_path.name
        if not extracted.is_file():
            msg = f"Archive {backup_name} did not contain {target_path.name}."
            raise BackupError(msg)
        extracted.replace(target_path)

    logger.info("Restore complete from: %s", backup_name)
    return backup_name
