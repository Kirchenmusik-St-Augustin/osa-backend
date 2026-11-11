# osa-backend

[Deutsch](README.de.md)

FastAPI backend for **OSA** ("Orchester-Einteilung") — the scheduling/casting
system for the church musicians of Kirchenmusik St. Augustin.

## Tech Stack

- **Runtime:** Python 3.14, FastAPI, SQLAlchemy (sync — deliberately not
  async, see `app/db/database.py`), Pydantic v2, arq (background/scheduled
  jobs, see [Scheduler](#scheduler) below)
- **Database:** PostgreSQL (UUIDv7 primary keys, native enums, CHECK and
  FK constraints, TIMESTAMPTZ columns)
- **Backup:** Koofr (WebDAV), see [Scheduler](#scheduler) and
  [Scripts](#scripts) below
- **Container:** Podman Quadlets (rootless systemd) — quadlets for every
  stage, including local dev, live in [`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)

## Development Setup

### Prerequisites

- Podman with the `osa-backend` container running — see
  [`osa-deploy`'s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.md#6-local-development)
  for how to set this up from a fresh clone (Quadlet config ends up under
  `~/.config/containers/systemd/osa/osa-backend/` on the dev host)
- Python dev dependencies are installed inside the container
  (`requirements-dev.txt`)
- Both lock files (`requirements.lock`, `requirements-dev.lock`) carry the
  hashes of every release file, and the image build and the pipeline install
  them with hash checking. Regenerate them with the command in their header
  (it includes `--generate-hashes`); a lock without hashes fails the tests
  and the build.

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
the real Alembic migrations — never against the production database. The
suite refuses to start unless that database is local (`localhost`,
`127.0.0.1` or `::1`) and named `osa_test` or `test`. See
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

Schema changes go through Alembic (`alembic/`). The entrypoint of the `prod`
image (`docker-entrypoint.sh`) runs `alembic upgrade head` on every start of
the web container, so a deploy needs no manual migration step. The dedicated
worker container shares the image but skips it (`SKIP_MIGRATIONS=true`): exactly
one container ever migrates. The `dev` image has no such entrypoint, run
`alembic upgrade head` by hand there (see
[`osa-deploy`'s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.md#6-local-development)). To
generate a new migration after changing a model:

```bash
podman exec osa-backend alembic revision --autogenerate -m "describe the change"
```

`alembic` takes `DATABASE_URL` from the application settings, so it needs the
same boot-critical variables as the app (`APP_ENVIRONMENT`, `CORS_ORIGINS`,
`SECRET_KEY`); the container and the pipeline provide them. `alembic check`
(also run by the pipeline after `alembic upgrade head`) fails when a model
and the migrated schema have drifted apart, for example an index that a
migration created but no model declares.

Always review the generated migration before committing it — autogenerate
can miss things Alembic doesn't detect on its own (renamed columns,
some constraint changes). The schema has already gone through a full
Postgres redesign (UUIDv7 primary keys, native enums, CHECK constraints,
FK constraints with explicit ON DELETE/UPDATE strategies, TIMESTAMPTZ
columns, a shared `updated_at` trigger function, ...) — new migrations
should follow that established style.

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
variables live vault-encrypted in the private site repository `osa-access`
(`sites/<stage>/secrets/osa-backend.env.j2`), see
[Secrets](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.md#71-secrets) in the `osa-deploy` README.

`GOOGLE_CLIENT_ID` is Tier 3 on both sides (backend and
[frontend](https://github.com/Kirchenmusik-St-Augustin/osa-frontend/blob/main/README.md#environment-variables)) — leave it
empty/unset on a stage where Google's Developer Console isn't configured
and Google Login is simply absent there: the frontend's button doesn't
render, and `require_setting()` (see `app/core/config.py`) only raises if
`/auth/google/callback`/`/auth/google/link` are somehow called anyway,
never at boot.

Two Tier 2 variables change security behaviour: `BCRYPT_ROUNDS` (work factor
of new password hashes, default 12; production never hashes below 12, the test
suite sets 4) and `REFRESH_COOKIE_SAMESITE` (`strict` by default, also
`lax` or `none`; use `none` only when the frontend and the API are served from
different registrable domains, the origin check on `/auth/refresh` applies
either way).

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
| `purge_old_request_logs` | daily 23:00 | `production` only | Deletes request-log rows older than 40 days and the user agents no log refers to, auth logs and sent mails older than a year, and sessions past their lifetime or idle for too long. |
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
/administrator/scheduler/backup/trigger`, `.../downsync/trigger`) only
queue a job for the worker and answer `202 Accepted`; the web process
never runs `pg_dump`/`pg_restore` itself. They are queued under the id of
the scheduled job (`backup_koofr`, `downsync`), so a trigger is dropped
while that job is still queued or running, and the outcome appears as the
job's last run on the scheduler page and as a `[triggered]` line in the
`arq.worker` log.

## Scripts

Operational scripts, run manually, from the repo root inside the running
worker container (`osa-backend-worker`): the Koofr credentials are passed to
the worker only, the web container stops with `KOOFR_USER is not set`:

| Script | Purpose |
|---|---|
| `scripts/backup_db.py` | Manually trigger a Koofr backup (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Restore the DB from a Koofr backup (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Router/service separation-of-concerns pre-commit check |

```bash
podman exec osa-backend-worker python scripts/backup_db.py --list
podman exec osa-backend-worker python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend-worker python scripts/restore_db.py --force
```

`restore_db.py` refuses to run under `APP_ENVIRONMENT=production` without
`--force`, because a restore overwrites the live database. Before it starts, the
script names the target database and the backup and asks for the database
name to be typed; `--yes` skips that question for unattended use. After a
restore, restart the backend pod (`systemctl --user restart
osa-backend-pod.service`): the running web container still holds connections
and schema cache of the replaced database. See
[Restore the database](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.md#34-restore-the-database) in the `osa-deploy`
README for the full disaster recovery runbook.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it
privately instead:

- through GitHub's private vulnerability reporting: the "Security and
  quality" tab of this repository, then "Report a vulnerability", or
- by e-mail to einteilung@hochamt.at.

Please include the affected version or commit, the steps to reproduce and
the impact you expect. We answer as soon as possible and keep you informed
while the problem is fixed.

## Branching

- `main` — protected, merge via PR only
- `development` — active development branch

## CI/CD

The pipeline (`.github/workflows/ci-cd.yml`) runs on every push to `main`,
every PR targeting `main`, weekly (Monday 06:00 UTC, CodeQL refresh), and
on manual dispatch:

1. **Lint & Format** — `ruff check` + `ruff format --check`
2. **Typecheck & Test** — `pyright` + `pytest --tb=short -q` + `alembic check`
3. **CodeQL Security Scan**
4. **Read-only Rootfs Smoke Test** — builds the `Dockerfile`'s `prod` target
   once, pushes it under a `-test` tag and runs the web and the worker
   container under the production restrictions (read-only root file system,
   no capabilities, `no-new-privileges`); fails on an unhealthy container or a
   read-only violation in the logs
5. **Build & Push Image** — only on `push`/`workflow_dispatch` started on
   `main` (never on PRs, other branches or the scheduled run), promotes the
   tested image by digest to
   `ghcr.io/kirchenmusik-st-augustin/osa-backend:latest` and
   `:${{ github.sha }}`; nothing is rebuilt

A pushed image reaches a running stage on its own, via
`podman-auto-update.timer` — or immediately, via `--tags deploy-backend`.
See [Day-2 deploy](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.md#52-day-2-deploy) in the `osa-deploy` README for that full
deploy flow; this repo doesn't run it.
