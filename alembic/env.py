from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.db.base  # registers every model with Base.metadata before autogenerate runs
from alembic import context
from app.core.config import get_settings, require_setting
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

# DATABASE_URL comes from app.core.config.Settings (validated, single source
# of truth across dev/test/CI/prod), not from alembic.ini. "%" is doubled
# because ConfigParser interpolates it, which would otherwise break
# URL-encoded credentials.
config.set_main_option(
    "sqlalchemy.url",
    require_setting(get_settings().database_url, "DATABASE_URL")
    .get_secret_value()
    .replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
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
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
