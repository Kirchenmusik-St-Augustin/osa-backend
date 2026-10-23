import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

from pydantic import BaseModel

import app.schemas
from app.schemas.auth import EmailKillSwitchStatusOutput
from app.schemas.base import IdLabelOutput, IdNameOutput
from app.schemas.statistics import StatisticsEmailOutput

_SCHEMA_DIR = Path(app.schemas.__file__).parent


def _models_declared_in_the_schema_package() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for info in pkgutil.iter_modules(app.schemas.__path__):
        module = importlib.import_module(f"app.schemas.{info.name}")
        models.extend(
            cls
            for _, cls in inspect.getmembers(module, inspect.isclass)
            if issubclass(cls, BaseModel) and cls.__module__ == module.__name__
        )
    return models


def test_a_pair_of_id_and_name_is_declared_only_once():
    twins = [
        f"{cls.__module__}.{cls.__name__}"
        for cls in _models_declared_in_the_schema_package()
        if set(cls.model_fields) == {"id", "name"} and cls is not IdNameOutput
    ]

    assert twins == []


def test_a_pair_of_id_and_label_is_declared_only_once():
    twins = [
        f"{cls.__module__}.{cls.__name__}"
        for cls in _models_declared_in_the_schema_package()
        if set(cls.model_fields) == {"id", "label"} and cls is not IdLabelOutput
    ]

    assert twins == []


def test_the_statistics_mail_status_is_the_kill_switch_status_plus_the_sent_count():
    assert issubclass(StatisticsEmailOutput, EmailKillSwitchStatusOutput)
    assert list(StatisticsEmailOutput.model_fields) == [
        *EmailKillSwitchStatusOutput.model_fields,
        "sent",
    ]


def test_schemas_do_not_import_from_the_service_layer():
    importers = []
    for path in sorted(_SCHEMA_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            importers.extend(
                path.name for module in modules if module.startswith("app.services")
            )

    assert importers == []
