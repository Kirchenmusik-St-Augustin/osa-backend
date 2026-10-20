import json
import pickle
from datetime import datetime

import pytest
from arq.jobs import deserialize_job_raw, serialize_job, serialize_result

from app.core.job_serialization import dumps_job, loads_job
from app.core.mailer import BookingCanceledMailEntry
from app.core.redacted import Redacted


def _entry(**overrides: object) -> BookingCanceledMailEntry:
    fields: dict[str, object] = {
        "ordinariumwork_artist_name": "Mozart",
        "ordinariumwork_name": "Requiem",
        "schedule": datetime(2026, 9, 1, 10, 0),  # noqa: DTZ001 -- naive wall-clock
        "location_name": "Dom",
        "location_address": None,
        "previous_status": 4,
        "position_name": "Sopran",
    }
    return BookingCanceledMailEntry(**{**fields, **overrides})  # pyright: ignore[reportArgumentType]


def _roundtrip(
    *args: object, **kwargs: object
) -> tuple[tuple[object, ...], dict[str, object]]:
    raw = serialize_job("job", args, kwargs, 1, 1000, serializer=dumps_job)
    _, restored_args, restored_kwargs, _, _ = deserialize_job_raw(
        raw, deserializer=loads_job
    )
    return tuple(restored_args), restored_kwargs


def test_plain_arguments_survive_the_roundtrip():
    args, kwargs = _roundtrip(
        ["a@example.com", "b@example.com"],
        "Erika Musterfrau",
        message="Grüß Gott\nZeile 2",
        phone=None,
    )

    assert args == (["a@example.com", "b@example.com"], "Erika Musterfrau")
    assert kwargs == {"message": "Grüß Gott\nZeile 2", "phone": None}


def test_redacted_argument_survives_and_stays_hidden():
    args, _ = _roundtrip("max@example.com", Redacted("https://example.com/r?token=abc"))

    restored = args[1]
    assert isinstance(restored, Redacted)
    assert restored.value == "https://example.com/r?token=abc"
    assert repr(restored) == "<redacted>"


@pytest.mark.parametrize("address", [None, "Domplatz 1"])
def test_mail_entry_survives_the_roundtrip(address: str | None):
    entry = _entry(location_address=address)

    args, _ = _roundtrip(["a@example.com"], "Erika", entry)

    assert args[2] == entry


def test_serialized_job_is_plain_json():
    raw = serialize_job(
        "job", (Redacted("secret-link"),), {}, 1, 1000, serializer=dumps_job
    )

    assert json.loads(raw)["a"] == [{"__type__": "Redacted", "value": "secret-link"}]


def test_result_of_a_failed_job_is_stored_as_text(caplog: pytest.LogCaptureFixture):
    # arq serializes the exception of a failed job as its result, even when
    # no result is kept; that must not raise and fall back to the placeholder.
    raw = serialize_result(
        "job",
        (),
        {},
        1,
        1000,
        False,
        RuntimeError("boom"),
        1000,
        1001,
        "ref",
        "queue",
        "job-id",
        serializer=dumps_job,
    )

    assert raw is not None
    assert json.loads(raw)["r"] == "RuntimeError('boom')"
    assert "error serializing result" not in caplog.text


def test_unsupported_argument_type_is_refused_on_enqueue():
    with pytest.raises(TypeError, match="cannot be serialized"):
        dumps_job({"a": [object()]})


def test_pickled_payload_is_never_executed(tmp_path):
    marker = tmp_path / "executed"

    class Exploit:
        def __reduce__(self):
            return (marker.write_text, ("x",))

    payload = pickle.dumps(Exploit())

    with pytest.raises(ValueError, match=r"(?i)utf-8|json|expecting"):
        loads_job(payload)
    assert not marker.exists()


def test_unknown_type_tag_is_refused():
    raw = json.dumps({"a": [{"__type__": "os.system", "value": "x"}]}).encode()

    with pytest.raises(ValueError, match="Unknown job argument type"):
        loads_job(raw)


@pytest.mark.parametrize(
    "tagged",
    [
        {"__type__": "Redacted", "value": 5},
        {"__type__": "Redacted"},
        {
            "__type__": "BookingCanceledMailEntry",
            "ordinariumwork_artist_name": "Mozart",
            "ordinariumwork_name": "Requiem",
            "schedule": "2026-09-01T10:00:00",
            "location_name": "Dom",
            "location_address": None,
            "previous_status": "4",
            "position_name": "Sopran",
        },
        {
            "__type__": "BookingCanceledMailEntry",
            "ordinariumwork_artist_name": "Mozart",
            "ordinariumwork_name": "Requiem",
            "schedule": "2026-09-01T10:00:00",
            "location_name": "Dom",
            "location_address": 7,
            "previous_status": 4,
            "position_name": "Sopran",
        },
        {
            "__type__": "BookingCanceledMailEntry",
            "ordinariumwork_artist_name": "Mozart",
            "ordinariumwork_name": "Requiem",
            "schedule": "2026-09-01T10:00:00",
            "location_name": "Dom",
            "location_address": None,
            "previous_status": True,
            "position_name": "Sopran",
        },
    ],
)
def test_tagged_object_with_wrong_field_types_is_refused(tagged: dict[str, object]):
    raw = json.dumps({"a": [tagged]}).encode()

    with pytest.raises(TypeError, match="must be"):
        loads_job(raw)


def test_payload_that_is_not_an_object_is_refused():
    with pytest.raises(TypeError, match="JSON object"):
        loads_job(b"[1, 2]")
