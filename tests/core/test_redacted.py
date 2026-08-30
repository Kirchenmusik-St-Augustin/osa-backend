import pickle

from app.core.redacted import Redacted


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
