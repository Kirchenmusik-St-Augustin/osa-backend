# osa-backend

FastAPI backend for **OSA** ("Orchester-Einteilung") — the scheduling/casting
system for the church musicians of Kirchenmusik St. Augustin. Migrates a
legacy Laravel/Inertia/Vue application; see [`CLAUDE.md`](../CLAUDE.md) for
the full migration phasing and coding standards.

## Tech Stack

- **Runtime:** Python 3.12, FastAPI, SQLAlchemy (sync — deliberately not
  async, see `app/db/database.py`), Pydantic v2, APScheduler
- **Database:** SQLite (Phase 1 — structurally identical to the legacy
  schema; PostgreSQL migration is Phase 2, not yet started, see
  [`CLAUDE.md`](../CLAUDE.md) section 3)
- **Backup:** Koofr (WebDAV), see [Scheduler](#scheduler) and
  [Scripts](#scripts) below
- **Container:** Podman Quadlets (rootless systemd) — production quadlets
  live in [`osa-deploy`](../osa-deploy)

## Development Setup

### Prerequisites

- Podman with the `osa-backend` container running (see Quadlet config under
  `~/.config/containers/systemd/osa/osa-backend/` on the dev host)
- Python dev dependencies are installed inside the container
  (`requirements-dev.txt`)

### After cloning

```bash
pre-commit install
```

Without this, commits bypass ruff/pyright/pytest entirely — the CI
pipeline runs the same checks, so a local pre-commit failure means CI would
have failed too.

### Running tests

```bash
podman exec osa-backend pytest --tb=short -q
```

The test suite runs against an isolated, throwaway SQLite file rebuilt from
`tests/fixtures/legacy_schema.sql` per session — never against the real
619 MB `database/database.sqlite`. Regenerate that fixture (only needed if
the legacy schema itself changes) with:

```bash
podman exec osa-backend python scripts/dump_test_schema.py
```

Coverage costs noticeable extra time (`coverage.py` + `greenlet` overhead)
— use `pytest -q --no-cov` for quick iteration, and only run the full
`--cov=app --cov-report=term-missing` before a commit/checkpoint.

### Linting, formatting & type checking

```bash
podman exec osa-backend ruff check .
podman exec osa-backend ruff format --check .
podman exec osa-backend ruff check --fix .      # auto-fix
podman exec osa-backend ruff format .           # auto-format

podman exec osa-backend python -m pyright

# Guards against business logic creeping back into routers (Router ->
# Service -> Model layering, see CLAUDE.md):
podman exec osa-backend python scripts/check_router_soc.py
```

## No Alembic in Phase 1

This repo has **no migrations tooling** (`alembic.ini`, `alembic/`) yet —
deliberately. Phase 1 keeps the schema structurally identical to the
legacy SQLite database (same tables/columns/types), so there is nothing to
migrate. Alembic + a real Postgres schema redesign (UUID PKs, native
enums, CHECK constraints, audit triggers, ...) is entirely Phase 2 —
see [`CLAUDE.md`](../CLAUDE.md) section 3 for the full boundary. Ruff/
pyright/coverage configs already carve out an `alembic/` exception for
when that lands, but nothing currently lives there.

## Environment Variables

Copy `.env.example` and fill in the required values:

```bash
cp .env.example .env
```

Settings are tiered (see `app/core/config.py`'s module docstring):

| Tier | Meaning | Examples |
|---|---|---|
| 1 | Boot-critical, validated at startup — process exits if missing/invalid | `APP_ENVIRONMENT`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS` |
| 2 | Optional, sane defaults, no boot-time validation | `APP_TIMEZONE`, mail sender identity, Koofr backup target/retention |
| 3 | Feature-required, no default — first real use raises, not boot | `SMTP_HOST`, `GOOGLE_CLIENT_ID`, `KOOFR_USER`/`KOOFR_PASSWORD` |

## Scheduler

Background jobs run via a single in-process APScheduler instance
(`app/core/scheduler.py`), started/stopped via `main.py`'s FastAPI
lifespan. A `pg_try_advisory_lock` guard prevents duplicate registration
across multiple Gunicorn workers — a no-op under SQLite (Phase 1, always a
single worker, see the `Dockerfile`'s `--workers 1`), relevant once
Phase 2 (Postgres) runs a real multi-worker production deployment.

| Job ID | Schedule | Stage | Purpose |
|---|---|---|---|
| `purge_stale_booking_requests` | hourly | all | Deletes stale open booking requests for past performances. |
| `notify_upcoming_booking_status` | daily 05:00 | all | Sends combined booking-status change mails. |
| `purge_expired_password_reset_tokens` | weekly, Sun 02:00 | all | Sweeps abandoned password-reset tokens. |
| `purge_old_request_logs` | daily 23:00 | all | Deletes request-log rows older than 40 days. |
| `backup_koofr` | daily, `BACKUP_HOUR`:`BACKUP_MINUTE` (default 03:00, `APP_TIMEZONE`) | `production` only (+ `BACKUP_ENABLED`) | `pg_dump` snapshot → Koofr WebDAV upload, then deletes backups older than `KOOFR_BACKUP_RETENTION_DAYS`. |

All five jobs run in `APP_TIMEZONE`
(`AsyncIOScheduler(timezone=get_app_timezone())`, see `app/core/scheduler.py`)
-- fixed 2026-08-13/14, see `app/core/datetime_utils.py::get_app_timezone()`
for the single shared source every timezone-aware call site (scheduler,
backup filenames/retention, mail subjects, logging) now resolves through.

`backup_koofr` is the only job gated by environment — it writes into a
Koofr path shared across every stage (dev/test/qa/production), so a single
settings toggle alone isn't enough to keep a non-prod process from writing
there.

## Scripts

Operational scripts, run manually, from the repo root inside the running
container:

| Script | Purpose |
|---|---|
| `scripts/backup_db.py` | Manually trigger a Koofr backup (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Restore the DB from a Koofr backup (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Router/service separation-of-concerns pre-commit check |
| `scripts/dump_test_schema.py` | Regenerate `tests/fixtures/legacy_schema.sql` from the real DB |

```bash
podman exec osa-backend python scripts/backup_db.py --list
podman exec osa-backend python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend python scripts/restore_db.py --force
```

`restore_db.py` refuses to run under `APP_ENVIRONMENT=production` without
`--force` — a restore overwrites the live database. See
[`osa-deploy`'s README](../osa-deploy/README.md) for the full disaster
recovery runbook.

## Branching

- `main` — protected, merge via PR only
- `development` — active development branch

## CI/CD

The pipeline (`.github/workflows/ci-cd.yml`) runs on every push to `main`,
every PR targeting `main`, weekly (Monday 06:00 UTC, CodeQL refresh), and
on manual dispatch:

1. **Lint & Format** — `ruff check` + `ruff format --check`
2. **Typecheck & Test** — `pyright` + `pytest --tb=short -q`
3. **CodeQL Security Scan**
4. **Build & Push Image** — only on `push`/`workflow_dispatch` (never on
   PRs or the scheduled run), builds the `Dockerfile`'s `prod` target,
   pushes `ghcr.io/kirchenmusik-st-augustin/osa-backend:latest` and
   `:${{ github.sha }}`

---

# Deutsch

FastAPI-Backend für **OSA** ("Orchester-Einteilung") — das Dienstplan-/
Besetzungssystem für die Kirchenmusiker von Kirchenmusik St. Augustin.
Migriert eine bestehende Laravel/Inertia/Vue-Anwendung; die vollständige
Phasenplanung und die Coding-Standards stehen in
[`CLAUDE.md`](../CLAUDE.md).

## Tech-Stack

- **Runtime:** Python 3.12, FastAPI, SQLAlchemy (synchron — bewusst nicht
  async, siehe `app/db/database.py`), Pydantic v2, APScheduler
- **Datenbank:** SQLite (Phase 1 — strukturgleich zum Legacy-Schema;
  die PostgreSQL-Migration ist Phase 2, noch nicht begonnen, siehe
  [`CLAUDE.md`](../CLAUDE.md) Abschnitt 3)
- **Backup:** Koofr (WebDAV), siehe [Scheduler](#scheduler-1) und
  [Skripte](#skripte) unten
- **Container:** Podman Quadlets (rootless systemd) — die
  Produktions-Quadlets liegen in [`osa-deploy`](../osa-deploy)

## Entwicklungs-Setup

### Voraussetzungen

- Podman mit laufendem `osa-backend`-Container (siehe Quadlet-Konfiguration
  unter `~/.config/containers/systemd/osa/osa-backend/` auf der
  Dev-Umgebung)
- Die Python-Dev-Abhängigkeiten sind im Container bereits installiert
  (`requirements-dev.txt`)

### Nach dem Klonen

```bash
pre-commit install
```

Ohne diesen Schritt umgehen Commits Ruff/Pyright/Pytest komplett — die
CI-Pipeline führt exakt dieselben Prüfungen aus, ein lokal fehlschlagender
Pre-Commit-Hook heißt also, dass CI ebenfalls fehlschlagen würde.

### Tests ausführen

```bash
podman exec osa-backend pytest --tb=short -q
```

Die Testsuite läuft gegen eine isolierte, wegwerfbare SQLite-Datei, die pro
Sitzung aus `tests/fixtures/legacy_schema.sql` neu aufgebaut wird — niemals
gegen die echte, 619 MB große `database/database.sqlite`. Dieses Fixture
(nur nötig, wenn sich das Legacy-Schema selbst ändert) neu erzeugen mit:

```bash
podman exec osa-backend python scripts/dump_test_schema.py
```

Coverage-Erhebung kostet spürbar mehr Zeit (`coverage.py`- +
`greenlet`-Overhead) — für schnelle Zwischenläufe `pytest -q --no-cov`
nutzen, den vollen `--cov=app --cov-report=term-missing`-Lauf nur vor
einem Commit/Checkpoint.

### Linting, Formatierung & Typprüfung

```bash
podman exec osa-backend ruff check .
podman exec osa-backend ruff format --check .
podman exec osa-backend ruff check --fix .      # automatisch beheben
podman exec osa-backend ruff format .           # automatisch formatieren

podman exec osa-backend python -m pyright

# Verhindert, dass Business-Logik zurück in die Router rutscht (Router ->
# Service -> Model-Schichtentrennung, siehe CLAUDE.md):
podman exec osa-backend python scripts/check_router_soc.py
```

## Kein Alembic in Phase 1

Dieses Repo hat (noch) **keine Migrations-Tools** (`alembic.ini`,
`alembic/`) — bewusst. Phase 1 hält das Schema strukturgleich zur
Legacy-SQLite-Datenbank (gleiche Tabellen/Spalten/Typen), es gibt also
nichts zu migrieren. Alembic + ein echtes Postgres-Schema-Redesign
(UUID-PKs, native Enums, CHECK-Constraints, Audit-Trigger, ...) ist
vollständig Phase 2 — die genaue Grenze steht in
[`CLAUDE.md`](../CLAUDE.md) Abschnitt 3. Ruff-/Pyright-/Coverage-Konfigs
halten bereits eine `alembic/`-Ausnahme für später bereit, aktuell liegt
dort aber nichts.

## Umgebungsvariablen

`.env.example` kopieren und die nötigen Werte eintragen:

```bash
cp .env.example .env
```

Die Settings sind gestuft (siehe den Docstring des Moduls
`app/core/config.py`):

| Stufe | Bedeutung | Beispiele |
|---|---|---|
| 1 | Boot-kritisch, beim Start validiert — Prozess beendet sich bei Fehlen/Ungültigkeit | `APP_ENVIRONMENT`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS` |
| 2 | Optional, sinnvolle Defaults, keine Validierung beim Boot | `APP_TIMEZONE`, Mail-Absenderidentität, Koofr-Backup-Ziel/-Retention |
| 3 | Feature-erforderlich, kein Default — erst bei echter Nutzung ein Fehler, nicht beim Boot | `SMTP_HOST`, `GOOGLE_CLIENT_ID`, `KOOFR_USER`/`KOOFR_PASSWORD` |

## Scheduler

Hintergrund-Jobs laufen über eine einzige, prozessinterne
APScheduler-Instanz (`app/core/scheduler.py`), gestartet/gestoppt über
`main.py`s FastAPI-Lifespan. Ein `pg_try_advisory_lock`-Schutz verhindert
Doppel-Registrierung über mehrere Gunicorn-Worker hinweg — unter SQLite
(Phase 1, immer nur ein Worker, siehe des `Dockerfile`s `--workers 1`) ein
No-Op, relevant erst, sobald Phase 2 (Postgres) einen echten
Multi-Worker-Produktivbetrieb fährt.

| Job-ID | Zeitplan | Stage | Zweck |
|---|---|---|---|
| `purge_stale_booking_requests` | stündlich | alle | Löscht veraltete offene Buchungsanfragen zu vergangenen Aufführungen. |
| `notify_upcoming_booking_status` | täglich 05:00 | alle | Versendet gebündelte Buchungsstatus-Änderungsmails. |
| `purge_expired_password_reset_tokens` | wöchentlich, So 02:00 | alle | Räumt verwaiste Passwort-Reset-Tokens auf. |
| `purge_old_request_logs` | täglich 23:00 | alle | Löscht Request-Log-Zeilen älter als 40 Tage. |
| `backup_koofr` | täglich, `BACKUP_HOUR`:`BACKUP_MINUTE` (Default 03:00, `APP_TIMEZONE`) | nur `production` (+ `BACKUP_ENABLED`) | `pg_dump`-Snapshot → Koofr-WebDAV-Upload, löscht danach Backups älter als `KOOFR_BACKUP_RETENTION_DAYS`. |

Alle fünf Jobs laufen in `APP_TIMEZONE`
(`AsyncIOScheduler(timezone=get_app_timezone())`, siehe `app/core/scheduler.py`)
— gefixt am 13./14.08.2026, siehe `app/core/datetime_utils.py::get_app_timezone()`
für die eine zentrale Quelle, über die jede zeitzonenbewusste Stelle
(Scheduler, Backup-Dateinamen/-Retention, Mail-Betreffzeilen, Logging)
jetzt läuft.

`backup_koofr` ist der einzige Job, der nach Umgebung gated wird — er
schreibt in einen Koofr-Pfad, der über alle Stages hinweg (Dev/Test/QA/
Produktion) gemeinsam genutzt wird, ein einzelner Settings-Schalter allein
reicht daher nicht, um einen Nicht-Prod-Prozess davon fernzuhalten, dort
hineinzuschreiben.

## Skripte

Betriebsskripte, manuell ausgeführt, vom Repo-Root aus im laufenden
Container:

| Skript | Zweck |
|---|---|
| `scripts/backup_db.py` | Löst manuell ein Koofr-Backup aus (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Stellt die DB aus einem Koofr-Backup wieder her (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Pre-Commit-Check für die Router-/Service-Schichtentrennung |
| `scripts/dump_test_schema.py` | Erzeugt `tests/fixtures/legacy_schema.sql` neu aus der echten DB |

```bash
podman exec osa-backend python scripts/backup_db.py --list
podman exec osa-backend python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend python scripts/restore_db.py --force
```

`restore_db.py` verweigert sich unter `APP_ENVIRONMENT=production` ohne
`--force` — ein Restore überschreibt die Live-Datenbank. Das vollständige
Disaster-Recovery-Runbook steht in
[`osa-deploy`s README](../osa-deploy/README.md).

## Branching

- `main` — geschützt, nur per PR mergen
- `development` — aktiver Entwicklungsbranch

## CI/CD

Die Pipeline (`.github/workflows/ci-cd.yml`) läuft bei jedem Push auf
`main`, jedem PR gegen `main`, wöchentlich (Montag 06:00 UTC,
CodeQL-Refresh) und bei manuellem Dispatch:

1. **Lint & Format** — `ruff check` + `ruff format --check`
2. **Typecheck & Test** — `pyright` + `pytest --tb=short -q`
3. **CodeQL Security Scan**
4. **Build & Push Image** — nur bei `push`/`workflow_dispatch` (nie bei
   PRs oder dem geplanten Lauf), baut das `Dockerfile`s `prod`-Target,
   pusht `ghcr.io/kirchenmusik-st-augustin/osa-backend:latest` und
   `:${{ github.sha }}`
