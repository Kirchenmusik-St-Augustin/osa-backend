import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.db.base  # registers every model with Base.metadata before autogenerate runs
from alembic import context
from app.db.database import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: alembic.ini's [loggers] section only
    # configures root/sqlalchemy/alembic -- the default True would silently
    # disable every other already-created logger (e.g. app.core.mailer's),
    # which conftest.py's session-scoped schema fixture would otherwise do
    # to the whole app for the rest of the test session (discovered via
    # caplog-based tests going silently empty after this call ran once).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# DATABASE_URL is read at runtime, not from alembic.ini -- keeps a single
# source of truth with app.core.config.Settings across every environment
# (dev/test/CI/prod), 1:1 vb-api's alembic/env.py.
config.set_main_option(
    "sqlalchemy.url",
    os.environ["DATABASE_URL"],
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
