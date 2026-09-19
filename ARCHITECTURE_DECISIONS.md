# Architecture Decisions

## ADR-1: Score field registry, cron catalog and instrument grid stay code

**Status:** accepted, 2026-09-18

Evaluated for a move into PostgreSQL tables: the score field registry
(`app/services/score_fields.py`, 94 fields), the cron catalog
(`app/worker/cron_config.py`, 6 jobs) and `INSTRUMENT_GRID` in the frontend's
`ScoreFieldsComponent.vue`.

**Decision:** all three remain configuration-as-code. No tables, no migration.

**Why**

- **Score registry:** it describes the schema, it does not parameterize it.
  `scores` is a flat table of 94 physical columns; the same facts are already
  enforced by native ENUMs, CHECK constraints and the Pydantic request model.
  Adding a field or a value always needs a migration, so a metadata table
  would be one more unenforced copy. Making it genuinely dynamic would mean
  EAV/JSONB and give up typed columns.
- **Cron catalog:** each job is a Python coroutine, so a row cannot create
  one. arq reads the schedule once at worker start, so a database value would
  not apply any sooner than an environment variable. Non-production stages
  restore the latest production backup every night: a schedule or `active`
  flag stored in the database would be overwritten with production's values
  and switch production-only jobs (booking mails, backup upload) on for
  dev/QA.
- **`INSTRUMENT_GRID`:** pure presentation of the printed archive card; the
  labels already come from the registry.

**Guardrails:** `tests/services/test_score_fields_consistency.py` pins the
registry to the request model, ENUM labels and columns;
`tests/worker/test_settings.py` requires a coroutine for every catalog entry.

**Revisit when**

- Disponents want to maintain a value list (e.g. *Sparte*) themselves:
  promote that one list to a lookup table with a foreign key, not the whole
  registry.
- Jobs become user- or tenant-defined: use a scheduler store that is excluded
  from the nightly restore.
