import logging


def setup_logging() -> None:
    """Configure root logging once, at process start."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
