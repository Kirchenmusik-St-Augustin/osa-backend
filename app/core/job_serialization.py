"""JSON job serializer shared by both sides of the arq queue.

arq pickles job data by default, and unpickling bytes that came out of the
queue is code execution: with pickle Valkey would be a code-execution
boundary instead of a data store. This serializer only produces and accepts
plain JSON values plus the two value types a job argument may carry
(`Redacted` and `BookingCanceledMailEntry`). Both are rebuilt field by field
from a tagged object; an unknown tag or a field of the wrong type is
refused, so no payload can instantiate anything else.

The web side (`app.core.arq_pool`) and the worker side
(`app.worker.settings.WorkerSettings`) must pass the same pair of functions.
"""

import json
from dataclasses import asdict
from datetime import datetime

from app.core.mailer import BookingCanceledMailEntry
from app.core.redacted import Redacted

_TYPE_KEY = "__type__"
_REDACTED_TAG = "Redacted"
_MAIL_ENTRY_TAG = "BookingCanceledMailEntry"


def _encode_value(value: object) -> object:
    if isinstance(value, BaseException):
        # arq stores the exception of a failed job as its result; the result is
        # only ever read for display, so its text is enough.
        return repr(value)
    if isinstance(value, Redacted):
        return {_TYPE_KEY: _REDACTED_TAG, "value": value.value}
    if isinstance(value, BookingCanceledMailEntry):
        fields: dict[str, object] = {
            **asdict(value),
            "schedule": value.schedule.isoformat(),
        }
        return {_TYPE_KEY: _MAIL_ENTRY_TAG, **fields}
    msg = f"Job arguments of type {type(value).__name__} cannot be serialized."
    raise TypeError(msg)


def _require_str(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    if not isinstance(value, str):
        msg = f"Job argument field {key!r} must be a string."
        raise TypeError(msg)
    return value


def _require_optional_str(fields: dict[str, object], key: str) -> str | None:
    if fields.get(key) is None:
        return None
    return _require_str(fields, key)


def _require_int(fields: dict[str, object], key: str) -> int:
    value = fields.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"Job argument field {key!r} must be an integer."
        raise TypeError(msg)
    return value


def _decode_object(fields: dict[str, object]) -> object:
    tag = fields.get(_TYPE_KEY)
    if tag is None:
        return fields
    if tag == _REDACTED_TAG:
        return Redacted(_require_str(fields, "value"))
    if tag == _MAIL_ENTRY_TAG:
        return BookingCanceledMailEntry(
            ordinariumwork_artist_name=_require_str(
                fields, "ordinariumwork_artist_name"
            ),
            ordinariumwork_name=_require_str(fields, "ordinariumwork_name"),
            schedule=datetime.fromisoformat(_require_str(fields, "schedule")),
            location_name=_require_str(fields, "location_name"),
            location_address=_require_optional_str(fields, "location_address"),
            previous_status=_require_int(fields, "previous_status"),
            position_name=_require_str(fields, "position_name"),
        )
    msg = f"Unknown job argument type {tag!r}."
    raise ValueError(msg)


def dumps_job(value: dict[str, object]) -> bytes:
    return json.dumps(value, default=_encode_value, separators=(",", ":")).encode()


def loads_job(raw: bytes) -> dict[str, object]:
    value = json.loads(raw, object_hook=_decode_object)
    if not isinstance(value, dict):
        msg = "A job payload must be a JSON object."
        raise TypeError(msg)
    return value
