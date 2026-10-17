import logging
import pickle
from typing import TYPE_CHECKING

from app.core.redacted import Redacted

if TYPE_CHECKING:
    import pytest


def test_repr_never_shows_the_wrapped_value():
    wrapped = Redacted("https://example.com/reset-password?token=super-secret")

    assert repr(wrapped) == "<redacted>"
    assert "super-secret" not in repr(wrapped)


def test_value_returns_the_original_string():
    wrapped = Redacted("https://example.com/reset-password?token=abc")

    assert wrapped.value == "https://example.com/reset-password?token=abc"


def test_survives_a_pickle_roundtrip():
    # arq's default job serializer is pickle.dumps (see
    # arq.jobs.serialize_job) -- every enqueue_job() argument, Redacted
    # included, must survive this round-trip unchanged.
    wrapped = Redacted("https://example.com/verify-email?token=xyz")

    restored = pickle.loads(pickle.dumps(wrapped))  # noqa: S301 -- round-tripping our own just-created object, not deserializing untrusted data

    assert restored.value == wrapped.value
    assert repr(restored) == "<redacted>"


def test_every_way_of_printing_the_value_hides_it(caplog: pytest.LogCaptureFixture):
    wrapped = Redacted("https://example.com/reset-password?token=super-secret")

    with caplog.at_level(logging.INFO):
        logging.getLogger("redacted-test").info("job args: %s %r", wrapped, (wrapped,))

    assert "super-secret" not in str(wrapped)
    assert "super-secret" not in f"{wrapped}"
    assert "super-secret" not in format(wrapped)
    assert "super-secret" not in caplog.text
    assert "<redacted>" in caplog.text
