import logging

from app.core.logging_config import setup_logging


def test_setup_logging_sets_root_level_info():
    setup_logging()

    assert logging.getLogger().level == logging.INFO
