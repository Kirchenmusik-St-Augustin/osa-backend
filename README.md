# osa-backend

FastAPI backend for **OSA** ("Orchester-Einteilung") — the scheduling/casting
system for the church musicians of Kirchenmusik St. Augustin.

## Tech Stack

- **Runtime:** Python 3.12, FastAPI, SQLAlchemy (sync — deliberately not
  async, see `app/db/database.py`), Pydantic v2, APScheduler
- **Database:** PostgreSQL (structurally identical to the legacy schema —
  a 1:1 transfer, not yet the full schema redesign)
- **Backup:** Koofr (WebDAV), see [Scheduler](#scheduler) and
  [Scripts](#scripts) below
- **Container:** Podman Quadlets (rootless systemd) — quadlets for every
  stage, including local dev, live in [`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)

## Development Setup

### Prerequisites

- Podman with the `osa-backend` container running — see
  [`osa-deploy`'s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy#local-development-environment)
  for how to set this up from a fresh clone (Quadlet config ends up under
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

The test suite runs against a dedicated PostgreSQL database
(`TEST_DATABASE_URL`, falling back to `DATABASE_URL`), schema built from
the real Alembic migrations — never against the production database. See
`tests/conftest.py`'s module docstring for the full isolation model
(per-test transaction + savepoint).

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
# Service -> Model layering):
podman exec osa-backend python scripts/check_router_soc.py
```

## Database Migrations

Schema changes go through Alembic (`alembic/`). `docker-entrypoint.sh`
runs `alembic upgrade head` automatically on every container start, so
there is no manual migration step in
[`osa-deploy`'s deploy runbook](https://github.com/Kirchenmusik-St-Augustin/osa-deploy) (Phase 2). To
generate a new migration after changing a model:

```bash
podman exec osa-backend alembic revision --autogenerate -m "describe the change"
```

Always review the generated migration before committing it — autogenerate
can miss things Alembic doesn't detect on its own (renamed columns,
some constraint changes). The current schema is still a structural 1:1
transfer of the legacy schema (same tables/columns/types) — a real
Postgres schema redesign (UUID PKs, native enums, CHECK constraints,
audit triggers, ...) is a separate, not-yet-started step.

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

`.env` is for local dev only. Production/test/qa never use it — the same
variables live vault-encrypted in [`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)'s
`secrets/<stage>/osa-backend.env.j2`, see its README's
[Maintaining secrets](https://github.com/Kirchenmusik-St-Augustin/osa-deploy#maintaining-secrets)
section.

`GOOGLE_CLIENT_ID` is Tier 3 on both sides (backend and
[frontend](https://github.com/Kirchenmusik-St-Augustin/osa-frontend#environment-variables)) — leave it
empty/unset on a stage where Google's Developer Console isn't configured
and Google Login is simply absent there: the frontend's button doesn't
render, and `require_setting()` (see `app/core/config.py`) only raises if
`/auth/google/callback`/`/auth/google/link` are somehow called anyway,
never at boot.

## Scheduler

Background jobs run in a dedicated arq worker container
(`osa-backend-worker`, entry point `arq app.worker.settings.WorkerSettings`),
separate from the web container -- both cron jobs and on-demand jobs
(former FastAPI `BackgroundTasks`, e.g. mail dispatch) run there
exclusively; the web container only enqueues on-demand jobs via
`enqueue_job()` and never runs a job itself. Every job's schedule/gating
is defined once in `app/worker/cron_config.py::build_cron_catalog()`,
shared by the actual arq registration (`app/worker/settings.py`) and the
admin Scheduler overview (`GET /administrator/scheduler/jobs`) so the two
can never drift apart.

| Job ID | Schedule | Stage | Purpose |
|---|---|---|---|
| `purge_stale_booking_requests` | hourly | all | Deletes stale open booking requests for past performances. |
| `notify_upcoming_booking_status` | daily 05:00 | `production` only | Sends combined booking-status change mails. |
| `purge_expired_password_reset_tokens` | weekly, Sun 02:00 | `production` only | Sweeps abandoned password-reset tokens. |
| `purge_old_request_logs` | daily 23:00 | `production` only | Deletes request-log rows older than 40 days. |
| `backup_koofr` | daily, `BACKUP_HOUR`:`BACKUP_MINUTE` (default 03:00, `APP_TIMEZONE`) | `production` only (+ `BACKUP_ENABLED`) | `pg_dump` snapshot → Koofr WebDAV upload, then deletes backups older than `KOOFR_BACKUP_RETENTION_DAYS`. |
| `downsync` | daily, one hour after `backup_koofr` (`BACKUP_HOUR + 1`:`BACKUP_MINUTE`) | non-`production` only | Restores this stage's local database from the latest production backup. |

All six jobs run in `APP_TIMEZONE` (`WorkerSettings.timezone =
get_app_timezone()`, see `app/worker/settings.py`), see
`app/core/datetime_utils.py::get_app_timezone()` for the single shared
source every timezone-aware call site (worker, backup filenames/
retention, mail subjects, logging) resolves through.

`notify_upcoming_booking_status`, `purge_expired_password_reset_tokens`,
and `purge_old_request_logs` are scoped to `production` because they
only matter there. `backup_koofr` and `downsync` are also
environment-gated, but for a different reason: `backup_koofr` writes
into a Koofr path shared across every stage, and `downsync` overwrites
this stage's local database from the latest production backup -- for
both, the gate is a real safety boundary, not just a relevance filter.

Every job-lifecycle line the worker logs under the `arq.worker` logger
(start, success, retry, abort, cancelled, failed, max-retries-exceeded)
gets a `[scheduled]` or `[triggered]` prefix from a small `logging.Filter`
installed once in `app/worker/settings.py`
(`app/worker/scheduled_or_triggered_log_filter.py`) — `[scheduled]` for a
run of one of this worker's own cron jobs, `[triggered]` for any job
fired on demand via `enqueue_job()` (registration/verification/
password-reset/notification mails). The manual "Trigger backup now" /
"Trigger downsync now" admin actions (`POST
/administrator/scheduler/backup/trigger`, `.../downsync/trigger`) call
`run_backup()`/`run_restore()` directly and synchronously, bypassing
`enqueue_job()` entirely — they never go through arq at all, so they
never appear in the `arq.worker` log, tagged or not.

## Scripts

Operational scripts, run manually, from the repo root inside the running
container:

| Script | Purpose |
|---|---|
| `scripts/backup_db.py` | Manually trigger a Koofr backup (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Restore the DB from a Koofr backup (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Router/service separation-of-concerns pre-commit check |

```bash
podman exec osa-backend python scripts/backup_db.py --list
podman exec osa-backend python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend python scripts/restore_db.py --force
```

`restore_db.py` refuses to run under `APP_ENVIRONMENT=production` without
`--force` — a restore overwrites the live database. See
[`osa-deploy`'s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy) for the full disaster
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

A pushed image reaches a running stage on its own, via
`podman-auto-update.timer` — or immediately, via `--tags deploy-backend`.
See [`osa-deploy`'s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy) for that full deploy
flow; this repo doesn't run it.

---

# Deutsch

FastAPI-Backend für **OSA** ("Orchester-Einteilung") — das Dienstplan-/
Besetzungssystem für die Kirchenmusiker von Kirchenmusik St. Augustin.

## Tech-Stack

- **Runtime:** Python 3.12, FastAPI, SQLAlchemy (synchron — bewusst nicht
  async, siehe `app/db/database.py`), Pydantic v2, APScheduler
- **Datenbank:** PostgreSQL (strukturgleich zum Legacy-Schema — ein
  1:1-Übertrag, noch nicht das volle Schema-Redesign)
- **Backup:** Koofr (WebDAV), siehe [Scheduler](#scheduler-1) und
  [Skripte](#skripte) unten
- **Container:** Podman Quadlets (rootless systemd) — die Quadlets für
  jede Stage, inklusive lokaler Entwicklung, liegen in
  [`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)

## Entwicklungs-Setup

### Voraussetzungen

- Podman mit laufendem `osa-backend`-Container — wie das von einem
  frischen Checkout aus aufgesetzt wird, steht in
  [`osa-deploy`s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy#lokale-entwicklungsumgebung)
  (die Quadlet-Konfiguration landet dabei unter
  `~/.config/containers/systemd/osa/osa-backend/` auf der Dev-Umgebung)
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

Die Testsuite läuft gegen eine dedizierte PostgreSQL-Datenbank
(`TEST_DATABASE_URL`, fällt auf `DATABASE_URL` zurück), Schema kommt aus
den echten Alembic-Migrationen — niemals gegen die Produktions-Datenbank.
Volles Isolationsmodell (Transaktion+Savepoint pro Test) siehe
`tests/conftest.py`s Modul-Docstring.

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
# Service -> Model-Schichtentrennung):
podman exec osa-backend python scripts/check_router_soc.py
```

## Datenbank-Migrationen

Schema-Änderungen laufen über Alembic (`alembic/`). `docker-entrypoint.sh`
führt bei jedem Container-Start automatisch `alembic upgrade head` aus,
kein manueller Migrationsschritt im
[Deploy-Runbook von `osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy) (Phase 2)
nötig. Neue Migration nach einer Modell-Änderung erzeugen:

```bash
podman exec osa-backend alembic revision --autogenerate -m "Änderung beschreiben"
```

Die generierte Migration immer vor dem Committen durchlesen — Autogenerate
erkennt nicht alles zuverlässig selbst (umbenannte Spalten, manche
Constraint-Änderungen). Das aktuelle Schema ist weiterhin ein struktureller
1:1-Übertrag des Legacy-Schemas (gleiche Tabellen/Spalten/Typen) — ein
echtes Postgres-Schema-Redesign (UUID-PKs, native Enums, CHECK-Constraints,
Audit-Trigger, ...) ist ein separater, noch nicht begonnener Schritt.

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

`.env` ist nur für lokale Entwicklung. Produktion/Test/QA nutzen es nie —
dieselben Variablen liegen dort vault-verschlüsselt in
[`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)s `secrets/<stage>/osa-backend.env.j2`, siehe
den Abschnitt [Secrets pflegen](https://github.com/Kirchenmusik-St-Augustin/osa-deploy#secrets-pflegen)
in dessen README.

`GOOGLE_CLIENT_ID` ist auf beiden Seiten Stufe 3 (Backend und
[Frontend](https://github.com/Kirchenmusik-St-Augustin/osa-frontend#umgebungsvariablen)) — auf einer
Stage, auf der die Google Developer Console nicht konfiguriert ist,
einfach leer/unset lassen, dann ist Google Login dort schlichtweg nicht
vorhanden: der Button im Frontend rendert nicht, und `require_setting()`
(siehe `app/core/config.py`) wirft nur dann, wenn
`/auth/google/callback`/`/auth/google/link` trotzdem irgendwie aufgerufen
werden — nie beim Boot.

## Scheduler

Hintergrund-Jobs laufen in einem dedizierten arq-Worker-Container
(`osa-backend-worker`, Entrypoint `arq app.worker.settings.WorkerSettings`),
getrennt vom Web-Container — sowohl Cron-Jobs als auch on-demand
ausgelöste Jobs (frühere FastAPI-`BackgroundTasks`, z.B. Mailversand)
laufen ausschließlich dort; der Web-Container reiht on-demand-Jobs nur
per `enqueue_job()` ein und führt selbst keinen Job aus. Zeitplan/Gating
jedes Jobs ist einmal zentral in `app/worker/cron_config.py::build_cron_catalog()`
definiert, geteilt von der tatsächlichen arq-Registrierung
(`app/worker/settings.py`) und der Admin-Scheduler-Übersicht
(`GET /administrator/scheduler/jobs`), damit beide nie auseinanderlaufen.

| Job-ID | Zeitplan | Stage | Zweck |
|---|---|---|---|
| `purge_stale_booking_requests` | stündlich | alle | Löscht veraltete offene Buchungsanfragen zu vergangenen Aufführungen. |
| `notify_upcoming_booking_status` | täglich 05:00 | nur `production` | Versendet gebündelte Buchungsstatus-Änderungsmails. |
| `purge_expired_password_reset_tokens` | wöchentlich, So 02:00 | nur `production` | Räumt verwaiste Passwort-Reset-Tokens auf. |
| `purge_old_request_logs` | täglich 23:00 | nur `production` | Löscht Request-Log-Zeilen älter als 40 Tage. |
| `backup_koofr` | täglich, `BACKUP_HOUR`:`BACKUP_MINUTE` (Default 03:00, `APP_TIMEZONE`) | nur `production` (+ `BACKUP_ENABLED`) | `pg_dump`-Snapshot → Koofr-WebDAV-Upload, löscht danach Backups älter als `KOOFR_BACKUP_RETENTION_DAYS`. |
| `downsync` | täglich, eine Stunde nach `backup_koofr` (`BACKUP_HOUR + 1`:`BACKUP_MINUTE`) | nur außerhalb `production` | Ersetzt die lokale Datenbank dieser Stage durch das letzte Production-Backup. |

Alle sechs Jobs laufen in `APP_TIMEZONE` (`WorkerSettings.timezone =
get_app_timezone()`, siehe `app/worker/settings.py`), siehe
`app/core/datetime_utils.py::get_app_timezone()` für die eine zentrale
Quelle, über die jede zeitzonenbewusste Stelle (Worker,
Backup-Dateinamen/-Retention, Mail-Betreffzeilen, Logging) läuft.

`notify_upcoming_booking_status`, `purge_expired_password_reset_tokens`
und `purge_old_request_logs` sind auf `production` beschränkt, weil sie
nur dort relevant sind. `backup_koofr` und `downsync` sind ebenfalls
umgebungsgegatet, aber aus einem anderen Grund: `backup_koofr` schreibt
in einen über alle Stages geteilten Koofr-Pfad, `downsync` überschreibt
die lokale Datenbank dieser Stage mit dem letzten Production-Backup —
bei beiden ist das Gate eine echte Sicherheitsgrenze, kein reiner
Relevanzfilter.

Jede Job-Lifecycle-Zeile, die der Worker über den `arq.worker`-Logger
loggt (Start, Erfolg, Retry, Abbruch, Cancelled, Fehlschlag,
Max-Retries-überschritten), bekommt über einen kleinen, einmalig in
`app/worker/settings.py` installierten `logging.Filter`
(`app/worker/scheduled_or_triggered_log_filter.py`) ein `[scheduled]`-
bzw. `[triggered]`-Präfix — `[scheduled]` für einen Lauf eines der
eigenen Cron-Jobs dieses Workers, `[triggered]` für jeden on-demand per
`enqueue_job()` ausgelösten Job (Registrierungs-/Verifizierungs-/
Passwort-Reset-/Benachrichtigungsmails). Die manuellen Admin-Aktionen
„Backup jetzt auslösen“ / „Downsync jetzt auslösen“ (`POST
/administrator/scheduler/backup/trigger`, `.../downsync/trigger`) rufen
`run_backup()`/`run_restore()` direkt und synchron auf, ohne
`enqueue_job()` — sie laufen komplett an arq vorbei und erscheinen daher
nie im `arq.worker`-Log, weder getaggt noch ungetaggt.

## Skripte

Betriebsskripte, manuell ausgeführt, vom Repo-Root aus im laufenden
Container:

| Skript | Zweck |
|---|---|
| `scripts/backup_db.py` | Löst manuell ein Koofr-Backup aus (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Stellt die DB aus einem Koofr-Backup wieder her (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Pre-Commit-Check für die Router-/Service-Schichtentrennung |

```bash
podman exec osa-backend python scripts/backup_db.py --list
podman exec osa-backend python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend python scripts/restore_db.py --force
```

`restore_db.py` verweigert sich unter `APP_ENVIRONMENT=production` ohne
`--force` — ein Restore überschreibt die Live-Datenbank. Das vollständige
Disaster-Recovery-Runbook steht in
[`osa-deploy`s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy).

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

Ein gepushtes Image erreicht eine laufende Stage von selbst, über
`podman-auto-update.timer` — oder sofort, über `--tags deploy-backend`.
Den vollständigen Deploy-Flow dazu beschreibt
[`osa-deploy`s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy); dieses Repo führt ihn
nicht selbst aus.
