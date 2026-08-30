"""Single source of truth for every cron-scheduled job's timing/gating --
consumed both by app.worker.settings.WorkerSettings (the actual arq
registration) and by app.services.scheduler_service.get_scheduled_jobs()
(the admin Scheduler overview, GET /administrator/scheduler/jobs), so the
two can never drift apart.

Explicit dataclass fields, not a generic dict[str, int | str]: Pyright
strict cannot reconcile a loosely-typed dict against arq's own precisely
per-field-typed cron()/next_cron() signatures. Field names mirror arq's
own cron() keyword arguments exactly (month/day/weekday/hour/minute/
second/microsecond) -- note arq's weekday strings differ from
APScheduler's: 'tues'/'thurs', not APScheduler's 'tue'/'thu'. Irrelevant
for the one job below using a weekday ('sun' is spelled identically in
both), but a real trap for any future job using Tuesday/Thursday -- a
wrong string crashes the worker at startup with ValueError, not at the
job's actual run time.
"""

from dataclasses import dataclass

from arq.typing import WeekdayOptionType

from app.core.config import Settings


@dataclass(frozen=True)
class CronSchedule:
    job_id: str
    description: str
    active: bool
    month: int | None = None
    day: int | None = None
    # WeekdayOptionType (arq's own alias) instead of a plain str: arq's
    # cron() only accepts its own Literal weekday spellings ('tues'/'thurs',
    # not 'tue'/'thu') -- a broader str type here would pass Pyright strict
    # but let a misspelled value slip through undetected until the worker
    # crashes with ValueError at startup.
    weekday: WeekdayOptionType = None
    hour: int | None = None
    minute: int | None = None
    second: int | None = 0
    microsecond: int = 123_456


def build_cron_catalog(settings: Settings) -> list[CronSchedule]:
    """Every job the former APScheduler-based start_scheduler() used to
    register, ported 1:1 -- same gating (is_production/backup_enabled),
    same cadence values."""
    is_production = settings.app_environment == "production"
    return [
        CronSchedule(
            job_id="purge_stale_booking_requests",
            description=(
                "Löscht stündlich offene Buchungsanfragen zu bereits "
                "vergangenen Terminen."
            ),
            active=True,
            minute=0,
        ),
        CronSchedule(
            job_id="notify_upcoming_booking_status",
            description=(
                "Versendet täglich um 05:00 Uhr eine Buchungsstatus-Mail "
                "für bevorstehende Termine. Nur in Production registriert."
            ),
            active=is_production,
            hour=5,
            minute=0,
        ),
        CronSchedule(
            job_id="purge_expired_password_reset_tokens",
            description=(
                "Löscht wöchentlich (So 02:00 Uhr) abgelaufene Passwort-"
                "Reset-Tokens. Nur in Production registriert."
            ),
            active=is_production,
            weekday="sun",
            hour=2,
            minute=0,
        ),
        CronSchedule(
            job_id="purge_old_request_logs",
            description=(
                "Löscht täglich um 23:00 Uhr Logbuch-Einträge, die älter "
                "als 40 Tage sind. Nur in Production registriert."
            ),
            active=is_production,
            hour=23,
            minute=0,
        ),
        CronSchedule(
            job_id="backup_koofr",
            description=(
                "Sichert die Datenbank täglich nach Koofr. Nur in "
                "Production und wenn BACKUP_ENABLED aktiv ist registriert."
            ),
            active=is_production and settings.backup_enabled,
            hour=settings.backup_hour,
            minute=settings.backup_minute,
        ),
        CronSchedule(
            job_id="downsync",
            description=(
                "Ersetzt nächtlich (eine Stunde nach backup_koofr) die "
                "lokale Datenbank dieser Stage durch das letzte "
                "Production-Backup. Nur außerhalb Production registriert."
            ),
            active=not is_production,
            hour=(settings.backup_hour + 1) % 24,
            minute=settings.backup_minute,
        ),
    ]
