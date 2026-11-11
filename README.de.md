# osa-backend

[English](README.md)

FastAPI-Backend für **OSA** ("Orchester-Einteilung") — das Dienstplan-/
Besetzungssystem für die Kirchenmusiker von Kirchenmusik St. Augustin.

## Tech-Stack

- **Runtime:** Python 3.14, FastAPI, SQLAlchemy (synchron — bewusst nicht
  async, siehe `app/db/database.py`), Pydantic v2, arq (Hintergrund-/
  Scheduled-Jobs, siehe [Scheduler](#scheduler) unten)
- **Datenbank:** PostgreSQL (UUIDv7-Primärschlüssel, native Enums, CHECK-
  und FK-Constraints, TIMESTAMPTZ-Spalten)
- **Backup:** Koofr (WebDAV), siehe [Scheduler](#scheduler) und
  [Skripte](#skripte) unten
- **Container:** Podman Quadlets (rootless systemd) — die Quadlets für
  jede Stage, inklusive lokaler Entwicklung, liegen in
  [`osa-deploy`](https://github.com/Kirchenmusik-St-Augustin/osa-deploy)

## Entwicklungs-Setup

### Voraussetzungen

- Podman mit laufendem `osa-backend`-Container — wie das von einem
  frischen Checkout aus aufgesetzt wird, steht in
  [`osa-deploy`s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.de.md#6-lokale-entwicklung)
  (die Quadlet-Konfiguration landet dabei unter
  `~/.config/containers/systemd/osa/osa-backend/` auf der Dev-Umgebung)
- Die Python-Dev-Abhängigkeiten sind im Container bereits installiert
  (`requirements-dev.txt`)
- Beide Lock-Dateien (`requirements.lock`, `requirements-dev.lock`) enthalten
  die Hashes jeder Release-Datei, Image-Build und Pipeline installieren sie mit
  Hash-Prüfung. Neu erzeugen mit dem Befehl in ihrem Kopf (er enthält
  `--generate-hashes`); eine Lock-Datei ohne Hashes lässt Tests und Build
  scheitern.

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
Die Suite startet nur, wenn diese Datenbank lokal liegt (`localhost`,
`127.0.0.1` oder `::1`) und `osa_test` oder `test` heißt. Volles Isolationsmodell (Transaktion+Savepoint pro Test) siehe
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

Schema-Änderungen laufen über Alembic (`alembic/`). Der Entrypoint des
`prod`-Images (`docker-entrypoint.sh`) führt bei jedem Start des Web-Containers
`alembic upgrade head` aus, ein Deploy braucht also keinen manuellen
Migrationsschritt. Der dedizierte Worker-Container teilt sich das Image,
überspringt das aber (`SKIP_MIGRATIONS=true`): Genau ein Container migriert.
Das `dev`-Image hat keinen solchen Entrypoint, dort `alembic upgrade head` von
Hand ausführen (siehe [`osa-deploy`s README](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.de.md#6-lokale-entwicklung)).
Neue Migration nach einer Modell-Änderung erzeugen:

```bash
podman exec osa-backend alembic revision --autogenerate -m "Änderung beschreiben"
```

`alembic` bezieht `DATABASE_URL` aus den Anwendungs-Settings und braucht daher
dieselben boot-kritischen Variablen wie die App (`APP_ENVIRONMENT`,
`CORS_ORIGINS`, `SECRET_KEY`); Container und Pipeline stellen sie bereit.
`alembic check` (läuft in der Pipeline nach `alembic upgrade head`) schlägt
fehl, wenn Modell und migriertes Schema auseinanderlaufen, zum Beispiel bei
einem Index, den eine Migration angelegt hat, den aber kein Modell deklariert.

Die generierte Migration immer vor dem Committen durchlesen — Autogenerate
erkennt nicht alles zuverlässig selbst (umbenannte Spalten, manche
Constraint-Änderungen). Das Schema hat bereits ein vollständiges
Postgres-Redesign durchlaufen (UUIDv7-Primärschlüssel, native Enums,
CHECK-Constraints, FK-Constraints mit expliziten ON-DELETE/UPDATE-
Strategien, TIMESTAMPTZ-Spalten, eine gemeinsame `updated_at`-Trigger-
Funktion, ...) — neue Migrationen sollten sich an diesem etablierten Stil
orientieren.

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
dieselben Variablen liegen dort vault-verschlüsselt im privaten
Site-Repository `osa-access` (`sites/<stage>/secrets/osa-backend.env.j2`), siehe
[Secrets](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.de.md#71-secrets) in der `osa-deploy`-README.

`GOOGLE_CLIENT_ID` ist auf beiden Seiten Stufe 3 (Backend und
[Frontend](https://github.com/Kirchenmusik-St-Augustin/osa-frontend/blob/main/README.de.md#umgebungsvariablen)) — auf einer
Stage, auf der die Google Developer Console nicht konfiguriert ist,
einfach leer/unset lassen, dann ist Google Login dort schlichtweg nicht
vorhanden: der Button im Frontend rendert nicht, und `require_setting()`
(siehe `app/core/config.py`) wirft nur dann, wenn
`/auth/google/callback`/`/auth/google/link` trotzdem irgendwie aufgerufen
werden — nie beim Boot.

Zwei Variablen der Stufe 2 ändern das Sicherheitsverhalten: `BCRYPT_ROUNDS`
(Work-Faktor neuer Passwort-Hashes, Default 12; Production hasht nie unter
12, die Testsuite setzt 4) und `REFRESH_COOKIE_SAMESITE` (Default `strict`,
außerdem `lax` oder `none`; `none` nur, wenn Frontend und API auf
verschiedenen registrierbaren Domains liegen, die Origin-Prüfung auf
`/auth/refresh` gilt in jedem Fall).

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
| `purge_old_request_logs` | täglich 23:00 | nur `production` | Löscht Request-Log-Zeilen älter als 40 Tage und die User-Agents, auf die kein Log mehr verweist, Auth-Logs und gesendete Mails älter als ein Jahr sowie Sessions, die ihre Lebensdauer überschritten haben oder zu lange ungenutzt waren. |
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
/administrator/scheduler/backup/trigger`, `.../downsync/trigger`) stellen
nur einen Job für den Worker in die Warteschlange und antworten mit
`202 Accepted`; der Web-Prozess führt `pg_dump`/`pg_restore` nie selbst
aus. Sie laufen unter der ID des geplanten Jobs (`backup_koofr`,
`downsync`), ein Auslöser wird also verworfen, solange dieser Job noch in
der Warteschlange liegt oder läuft; das Ergebnis erscheint als letzter
Lauf des Jobs auf der Scheduler-Seite und als `[triggered]`-Zeile im
`arq.worker`-Log.

## Skripte

Betriebsskripte, manuell ausgeführt, vom Repo-Root aus im laufenden
Worker-Container (`osa-backend-worker`): Die Koofr-Zugangsdaten bekommt nur
der Worker, der Web-Container bricht mit `KOOFR_USER is not set` ab:

| Skript | Zweck |
|---|---|
| `scripts/backup_db.py` | Löst manuell ein Koofr-Backup aus (`--list`, `--cleanup`, `--cleanup --dry-run`) |
| `scripts/restore_db.py` | Stellt die DB aus einem Koofr-Backup wieder her (`--list`, `--backup-name NAME`, `--force`) |
| `scripts/check_router_soc.py` | Pre-Commit-Check für die Router-/Service-Schichtentrennung |

```bash
podman exec osa-backend-worker python scripts/backup_db.py --list
podman exec osa-backend-worker python scripts/backup_db.py --cleanup --dry-run
podman exec -it osa-backend-worker python scripts/restore_db.py --force
```

`restore_db.py` verweigert sich unter `APP_ENVIRONMENT=production` ohne
`--force`, denn ein Restore überschreibt die Live-Datenbank. Vor dem Start nennt
das Skript die Ziel-Datenbank und das Backup und verlangt, dass der Name der
Datenbank eingetippt wird; `--yes` überspringt diese Rückfrage für den
unbeaufsichtigten Betrieb. Nach einem Restore den Backend-Pod neu starten
(`systemctl --user restart osa-backend-pod.service`): Der laufende
Web-Container hält noch Verbindungen und Schema-Cache der ersetzten Datenbank.
Das vollständige Disaster-Recovery-Runbook steht unter
[Datenbank wiederherstellen](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.de.md#34-datenbank-wiederherstellen) in der
`osa-deploy`-README.

## Sicherheitslücke melden

Bitte kein öffentliches Issue für ein Sicherheitsproblem eröffnen, sondern
es privat melden:

- über die private Schwachstellenmeldung von GitHub: Reiter "Security and
  quality" dieses Repositorys, dann "Report a vulnerability", oder
- per E-Mail an einteilung@hochamt.at.

Bitte die betroffene Version oder den Commit, die Schritte zur
Reproduktion und die erwartete Auswirkung angeben. Wir antworten so
schnell wie möglich und halten dich über die Behebung auf dem Laufenden.

## Branching

- `main` — geschützt, nur per PR mergen
- `development` — aktiver Entwicklungsbranch

## CI/CD

Die Pipeline (`.github/workflows/ci-cd.yml`) läuft bei jedem Push auf
`main`, jedem PR gegen `main`, wöchentlich (Montag 06:00 UTC,
CodeQL-Refresh) und bei manuellem Dispatch:

1. **Lint & Format** — `ruff check` + `ruff format --check`
2. **Typecheck & Test** — `pyright` + `pytest --tb=short -q` + `alembic check`
3. **CodeQL Security Scan**
4. **Read-only Rootfs Smoke Test** — baut das `prod`-Target des `Dockerfile`s
   einmal, pusht es unter einem `-test`-Tag und startet den Web- und den
   Worker-Container unter den Produktionsauflagen (schreibgeschütztes
   Root-Dateisystem, keine Capabilities, `no-new-privileges`); schlägt bei einem
   ungesunden Container oder einer Read-only-Verletzung in den Logs fehl
5. **Build & Push Image** — nur bei `push`/`workflow_dispatch`, die auf `main`
   gestartet wurden (nie bei PRs, anderen Branches oder dem geplanten Lauf),
   befördert das getestete Image per Digest nach
   `ghcr.io/kirchenmusik-st-augustin/osa-backend:latest` und
   `:${{ github.sha }}`; es wird nichts neu gebaut

Ein gepushtes Image erreicht eine laufende Stage von selbst, über
`podman-auto-update.timer` — oder sofort, über `--tags deploy-backend`.
Den vollständigen Deploy-Flow dazu beschreibt
[Deploy im Tagesbetrieb](https://github.com/Kirchenmusik-St-Augustin/osa-deploy/blob/main/README.de.md#52-deploy-im-tagesbetrieb) in der
`osa-deploy`-README; dieses Repo führt ihn nicht selbst aus.
