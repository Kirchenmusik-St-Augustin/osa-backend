"""Every model that carries `created_at` or `updated_at` gets both from the
shared TimestampColumns mixin, so the definition (type, default,
trigger-managed update column) cannot drift between tables."""

import importlib
import pkgutil

import pytest
from sqlalchemy import DateTime

import app.db.models as models_package
from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns


def _mapped_classes() -> list[type]:
    for module in pkgutil.iter_modules(models_package.__path__):
        importlib.import_module(f"{models_package.__name__}.{module.name}")
    return sorted(
        (mapper.class_ for mapper in Base.registry.mappers),
        key=lambda cls: cls.__name__,
    )


_MODELS = _mapped_classes()


def test_the_models_are_registered():
    assert len(_MODELS) > 20


@pytest.mark.parametrize("model", _MODELS, ids=lambda cls: cls.__name__)
def test_a_model_has_the_timestamp_columns_exactly_when_it_uses_the_mixin(model: type):
    columns = model.__table__.columns  # type: ignore[attr-defined]
    has_timestamp_columns = "created_at" in columns or "updated_at" in columns

    assert has_timestamp_columns == issubclass(model, TimestampColumns)


@pytest.mark.parametrize(
    "model",
    [model for model in _MODELS if issubclass(model, TimestampColumns)],
    ids=lambda cls: cls.__name__,
)
def test_the_timestamp_columns_are_timestamptz_with_the_default_and_trigger_split(
    model: type,
):
    columns = model.__table__.columns  # type: ignore[attr-defined]
    created_at, updated_at = columns["created_at"], columns["updated_at"]

    assert isinstance(created_at.type, DateTime)
    assert created_at.type.timezone is True
    assert created_at.server_default is not None
    assert created_at.nullable is False
    assert isinstance(updated_at.type, DateTime)
    assert updated_at.type.timezone is True
    assert updated_at.server_default is None
    assert updated_at.server_onupdate is not None
    assert updated_at.nullable is True
