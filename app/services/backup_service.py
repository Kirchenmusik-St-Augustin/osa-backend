"""PostgreSQL -> Koofr WebDAV backup/restore -- functional equivalent of
Legacy's OsaScheduleBackupProdDB.php Artisan command, and this module's
own file-copy-based predecessor.

Filenames are stage-prefixed (`{app_environment}-{timestamp}[-manual].dump`,
1:1 the vb-fastapi-vue sister project's `run_backup()` naming, User decision
2026-08-13) -- unchanged convention, only the extension moved from `.tar.gz`
(a tarred file copy) to `.dump` (pg_dump's own `--format=custom`
output, already a single binary file, nothing to tar). Backups created
before the Postgres cutover keep their old `.tar.gz` names on Koofr and no
longer match _FILENAME_PATTERN -- same accepted, documented naming break as
the 2026-08-13 stage-prefix change before it (see git history), not a
special case this module needs to handle.

Uses raw WebDAV HTTP verbs via `requests` (already a pinned dependency)
instead of shelling out to rclone (what the existing restore script does)
or adding a dedicated WebDAV client library -- no new dependency, no
subprocess/shell-escaping surface for the upload/download/list/delete side.
pg_dump/pg_restore/psql themselves are unavoidably subprocesses (no pure-
Python equivalent exists) -- 1:1 vb-api's `_run_pg_subprocess()` pattern,
including its stderr-surfacing fix (a bare CalledProcessError hides exactly
the detail that matters for debugging a failed disaster-recovery run).

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
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import requests
from sqlalchemy.engine import make_url

from app.core.config import get_settings, require_setting
from app.core.datetime_utils import local_now
from app.db.database import engine

logger = logging.getLogger(__name__)

# Sort-key fallback for a name that (per _FILENAME_PATTERN's own guarantee)
# never actually fails to parse -- keeps list_backups()'s sort key
# non-Optional without a runtime assert. Naive, matching local_now()'s own
# naive Vienna wall-clock convention -- see _parse_backup_timestamp() below.
_EPOCH = datetime.min  # noqa: DTZ901

_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
# Stage-prefixed, optionally "-manual"-suffixed -- 1:1 vb-api's
# f"{app_environment}-{timestamp}{suffix}" naming (User decision,
# 2026-08-13, see module docstring). `stage` is intentionally not
# constrained to Settings' exact _VALID_ENVIRONMENTS set here -- this
# pattern only needs to recognize OUR OWN generated filenames well enough
# to extract the timestamp, not to validate the settings enum.
_FILENAME_PATTERN = re.compile(
    r"^(?P<stage>[a-z]+)-(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"
    r"(?:-manual)?\.dump$"
)
_DAV_HREF_TAG = "{DAV:}href"


class BackupError(Exception):
    """Raised for any backup/restore failure -- the one exception type
    callers (scripts/backup_db.py, scripts/restore_db.py,
    app.services.backup_jobs) ever need to catch."""


def _require_postgres(database_url: str) -> None:
    if not database_url.startswith("postgresql"):
        msg = f"Backup/restore requires a PostgreSQL DATABASE_URL, got: {database_url}"
        raise BackupError(msg)


def _resolve_pg_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        msg = f"'{name}' not found in PATH. Install postgresql-client."
        raise BackupError(msg)
    return path


def _parse_db_url(database_url: str) -> tuple[str, str, str, int, str]:
    """Return (host, username, password, port, dbname).

    Uses SQLAlchemy's own connection-string parser (the same one
    create_engine(DATABASE_URL) uses elsewhere in this app) rather than
    urllib.parse.urlparse -- the latter treats the first '/' after '://'
    as the start of the path, so a password containing '/' (common in
    randomly-generated passwords) makes it misparse the whole netloc.
    """
    url = make_url(database_url)
    return (
        url.host or "localhost",
        url.username or "",
        url.password or "",
        url.port or 5432,
        url.database or "",
    )


def _build_pg_env(password: str) -> dict[str, str]:
    return {**os.environ, "PGPASSWORD": password}


def _run_pg_subprocess(
    args: list[str], env: dict[str, str], tool_name: str
) -> subprocess.CompletedProcess[bytes]:
    """Run a pg_dump/pg_restore/psql subprocess.

    On failure, raises BackupError with the tool's actual stderr -- a bare
    subprocess.CalledProcessError hides stderr from the caller, which makes
    a disaster-recovery script undebuggable exactly when it matters most.
    """
    try:
        return subprocess.run(args, capture_output=True, env=env, check=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        stderr = (
            exc.stderr.decode("utf-8", errors="replace").strip()
            if exc.stderr
            else "(no stderr captured)"
        )
        msg = f"{tool_name} failed (exit {exc.returncode}): {stderr}"
        raise BackupError(msg) from exc


def _retry_transient_koofr_request[T](
    operation: Callable[[], T], *, attempts: int = 3, base_delay: float = 1.0
) -> T:
    """Retry a Koofr WebDAV read/delete call a few times with exponential
    backoff.

    Guards against transient network blips and momentary 5xx responses on
    the calls most exposed to them. Deliberately NOT applied to
    _upload_to_koofr(): a failed backup upload is safe to simply fail and
    retry the whole backup job on the next scheduled run, whereas a
    restore/list/cleanup call failing mid-operation is the more disruptive
    case worth smoothing over here.
    """
    for attempt in range(attempts - 1):
        try:
            return operation()
        except requests.RequestException as exc:
            delay = base_delay * (2**attempt)
            logger.warning(
                "Transient Koofr request error on attempt %d/%d, retrying in %.0fs: %s",
                attempt + 1,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    return operation()  # final attempt -- let any RequestException propagate


def run_backup(*, manual: bool = False) -> str:
    """Dump the Postgres database (pg_dump --format=custom), upload to Koofr.

    manual=True tags the filename with a "-manual" suffix, distinguishing
    ad-hoc backups (admin-triggered API call, CLI script) from the ones the
    scheduled backup_koofr job produces unsuffixed -- 1:1 vb-api's
    run_backup(manual=...).

    Returns the uploaded archive's filename. Raises BackupError on any
    failure -- nothing is left behind on Koofr on failure, the upload is
    the last step.
    """
    database_url = require_setting(get_settings().database_url, "DATABASE_URL")
    _require_postgres(database_url)
    host, user, password, port, dbname = _parse_db_url(database_url)

    timestamp = local_now().strftime(_TIMESTAMP_FORMAT)
    suffix = "-manual" if manual else ""
    archive_name = f"{get_settings().app_environment}-{timestamp}{suffix}.dump"

    logger.info("Creating pg_dump snapshot: %s", archive_name)
    pg_dump = _resolve_pg_tool("pg_dump")
    result = _run_pg_subprocess(
        [
            pg_dump,
            "--format=custom",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            f"--dbname={dbname}",
        ],
        env=_build_pg_env(password),
        tool_name="pg_dump",
    )

    logger.info("Uploading backup to Koofr: %s", archive_name)
    _upload_to_koofr(archive_name, result.stdout)

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


def list_backups(*, stage: str | None = None) -> list[str]:
    """Sorted (oldest-first, by parsed timestamp) backup filenames
    currently on Koofr, via WebDAV PROPFIND (Depth 1).

    Sorts by _parse_backup_timestamp(), NOT by plain string order: since
    filenames are stage-prefixed, a raw sorted() would order by stage name
    first (e.g. every "test-..." name would sort after every
    "production-..." one regardless of actual age) -- exactly the latent
    weakness vb-api's own S3-key sort has, deliberately not replicated
    here since it would silently break run_restore()'s "latest backup"
    auto-selection across differently-staged backups sharing this one
    Koofr path.

    `stage`, when given, restricts the result to backups created by that
    exact stage (e.g. "production") -- used by the downsync job/trigger to
    find "the latest PRODUCTION backup" rather than the latest backup
    overall, since a manually-triggered backup is callable from any stage
    and lands in this same shared Koofr path too (see
    app.api.router_includes.scheduler.trigger_backup's docstring)."""
    user, password = _koofr_auth()
    propfind_body = (
        '<?xml version="1.0"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>'
    )

    def _do_propfind() -> requests.Response:
        response = requests.request(
            "PROPFIND",
            _koofr_url(),
            data=propfind_body,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            auth=(user, password),
            timeout=30,
        )
        response.raise_for_status()
        return response

    try:
        response = _retry_transient_koofr_request(_do_propfind)
    except requests.RequestException as exc:
        msg = f"Koofr directory listing failed: {exc}"
        raise BackupError(msg) from exc
    names = _parse_backup_filenames(response.text)
    if stage is not None:
        names = [name for name in names if _parse_backup_stage(name) == stage]
    return sorted(names, key=lambda name: _parse_backup_timestamp(name) or _EPOCH)


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


# NOTE (2026-08-14): both the filename timestamp (run_backup()) and the
# retention cutoff (cleanup_old_backups()) switched from datetime.now(UTC)
# to local_now() -- Settings.app_timezone wall-clock, matching the
# backup_koofr scheduler trigger's own timezone. Pre-2026-08-14 filenames
# are genuinely UTC-stamped from before this fix; the resulting <=2h skew
# for those older names is negligible against both the >=daily backup
# cadence (their order relative to newer entries is unaffected across
# calendar days) and the 28-day default retention window (~0.3% skew) --
# no backfill/rename of already-uploaded names is needed.
def _parse_backup_timestamp(name: str) -> datetime | None:
    match = _FILENAME_PATTERN.match(name)
    if match is None:
        return None
    # Deliberately naive -- see the module-level NOTE above for why this
    # stays unattached to any tzinfo.
    return datetime.strptime(match.group("timestamp"), _TIMESTAMP_FORMAT)  # noqa: DTZ007


def _parse_backup_stage(name: str) -> str | None:
    """Extract the stage prefix (e.g. "production") from a backup filename,
    reusing the same named group _FILENAME_PATTERN already defines --
    list_backups(stage=...)'s filter, kept DRY with the timestamp parser
    above instead of re-deriving the naming convention a second time."""
    match = _FILENAME_PATTERN.match(name)
    return match.group("stage") if match else None


def cleanup_old_backups(*, dry_run: bool = False) -> list[str]:
    """Delete Koofr backups older than koofr_backup_retention_days
    (default 28 = Legacy's hardcoded 4 weeks).

    Returns the filenames that were deleted (or, if dry_run=True, that
    WOULD be deleted -- nothing is actually removed in that case). Names
    that don't match the expected pattern are never touched.
    """
    retention_days = get_settings().koofr_backup_retention_days
    cutoff = local_now() - timedelta(days=retention_days)
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

    def _do_delete() -> requests.Response:
        response = requests.delete(
            _koofr_url(filename), auth=(user, password), timeout=30
        )
        response.raise_for_status()
        return response

    try:
        _retry_transient_koofr_request(_do_delete)
    except requests.RequestException as exc:
        msg = f"Koofr delete failed for {filename}: {exc}"
        raise BackupError(msg) from exc


def _wipe_public_schema(
    host: str, user: str, password: str, port: int, dbname: str
) -> None:
    """Drop and recreate the 'public' schema before a full restore.

    pg_restore --clean computes DROP order from the dump's dependency
    graph, which can get self-referencing/cross foreign keys wrong -- it
    then aborts that one DROP with "cannot drop constraint ... because
    other objects depend on it", and pg_restore's default error-tolerant
    behavior silently continues past the failure, leaving the target
    schema in an inconsistent, partially-restored state. Wiping the schema
    upfront and restoring without --clean sidesteps the ordering problem
    entirely -- there is nothing left to drop, so no DROP order can ever
    be wrong. 1:1 vb-api's own fix for the identical failure mode
    (observed there in practice against a real production dump).

    DROP SCHEMA needs an ACCESS EXCLUSIVE lock, which any other session
    with an open transaction on this database can block. Terminating every
    other session first makes lock acquisition deterministic instead of a
    timing race -- any session still using the old schema is about to get
    errors the instant it's dropped anyway. The scheduler's own
    advisory-lock-holding connection (see _acquire_scheduler_lock() in
    app.core.scheduler) is deliberately spared -- it never touches a
    table, so it can never conflict with DROP SCHEMA, and terminating it
    would silently stop this worker's scheduled jobs until the next
    restart. lock_timeout is a safety net for a new connection arriving in
    the brief window between the terminate and the DROP SCHEMA -- a fast,
    clearly logged failure instead of an unbounded hang.
    """
    psql = _resolve_pg_tool("psql")
    _run_pg_subprocess(
        [
            psql,
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            f"--dbname={dbname}",
            "-c",
            (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid != pg_backend_pid() "
                "AND query NOT ILIKE '%pg_try_advisory_lock%'; "
                "SET lock_timeout = '5s'; DROP SCHEMA public CASCADE; "
                "CREATE SCHEMA public;"
            ),
        ],
        env=_build_pg_env(password),
        tool_name="psql",
    )


def _verify_restore_populated(
    host: str, user: str, password: str, port: int, dbname: str
) -> None:
    """Raise BackupError if the just-restored database has zero rows.

    A pg_restore that exits 0 does not guarantee any rows actually landed.
    ANALYZE refreshes planner statistics immediately after the bulk load,
    then this sums row-count estimates across every table in 'public' --
    table-agnostic on purpose, this module has no business-domain
    knowledge of which specific tables should hold data.
    """
    psql = _resolve_pg_tool("psql")
    _run_pg_subprocess(
        [
            psql,
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            f"--dbname={dbname}",
            "-c",
            "ANALYZE;",
        ],
        env=_build_pg_env(password),
        tool_name="psql",
    )
    result = _run_pg_subprocess(
        [
            psql,
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            f"--dbname={dbname}",
            "--tuples-only",
            "--no-align",
            "-c",
            (
                "SELECT COALESCE(SUM(n_live_tup), 0)::bigint FROM"
                " pg_stat_user_tables WHERE schemaname = 'public';"
            ),
        ],
        env=_build_pg_env(password),
        tool_name="psql",
    )
    total_rows = int(result.stdout.strip())
    if total_rows == 0:
        msg = (
            "Restore completed but the database has zero rows across all "
            "tables in 'public' -- treating this as a failed restore."
        )
        raise BackupError(msg)


def run_restore(*, backup_name: str | None = None, force: bool = False) -> str:
    """Download a Koofr backup and restore it into the live Postgres database.

    Requires force=True when APP_ENVIRONMENT=production -- a restore
    overwrites the live database.

    Calls engine.dispose() after the restore: _wipe_public_schema() above
    terminates every other session on this database (except the
    scheduler's advisory-lock connection), including any this app's own
    connection pool was holding idle. pool_pre_ping=True (see
    app.db.database) would eventually catch and transparently replace each
    of those on next use anyway, but disposing the whole pool immediately
    is simpler than waiting for that to happen one connection at a time.
    """
    database_url = require_setting(get_settings().database_url, "DATABASE_URL")
    _require_postgres(database_url)

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

    user, password = _koofr_auth()

    def _do_download() -> requests.Response:
        response = requests.get(
            _koofr_url(backup_name), auth=(user, password), timeout=120
        )
        response.raise_for_status()
        return response

    try:
        response = _retry_transient_koofr_request(_do_download)
    except requests.RequestException as exc:
        msg = f"Koofr download failed for {backup_name}: {exc}"
        raise BackupError(msg) from exc

    host, db_user, db_password, port, dbname = _parse_db_url(database_url)
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    logger.info("Restoring DB from backup: %s", backup_name)
    pg_restore = _resolve_pg_tool("pg_restore")
    try:
        _wipe_public_schema(host, db_user, db_password, port, dbname)
        _run_pg_subprocess(
            [
                pg_restore,
                f"--host={host}",
                f"--port={port}",
                f"--username={db_user}",
                f"--dbname={dbname}",
                tmp_path,
            ],
            env=_build_pg_env(db_password),
            tool_name="pg_restore",
        )
        _verify_restore_populated(host, db_user, db_password, port, dbname)
    finally:
        Path(tmp_path).unlink()

    engine.dispose()
    logger.info("Restore complete from: %s", backup_name)
    return backup_name
