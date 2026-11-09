"""Loads one Alembic revision file and runs its upgrade or downgrade inside
the transaction of a test session, so a data migration can be tested against
rows the test created and is rolled back with the test."""

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

if TYPE_CHECKING:
    from types import ModuleType

    from sqlalchemy.orm import Session

_VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"


def load_migration(file_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(file_name, _VERSIONS / file_name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(
    db: Session, file_name: str, direction: Literal["upgrade", "downgrade"] = "upgrade"
) -> None:
    db.flush()
    module = load_migration(file_name)
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(module, direction)()
    db.expire_all()
