"""Valid request bodies of the forms that carry a person's name and phone
number, for tests that vary one field at a time."""

from typing import TYPE_CHECKING

from app.schemas.auth import RegisterRequest
from app.schemas.ordinariumwork import OrdinariumworkRequest
from app.schemas.performance import PerformanceRequest
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.user import UserRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

_PERSON = {
    "surname": "Muster",
    "givenname": "Maria",
    "email": "maria@example.com",
    "phone": "+43 664 1234567",
}


def _register(**fields: object) -> BaseModel:
    return RegisterRequest.model_validate(
        {
            **_PERSON,
            "password": "Passw0rd1",
            "password_confirmation": "Passw0rd1",
            **fields,
        }
    )


def _profile(**fields: object) -> BaseModel:
    return ProfileUpdateRequest.model_validate(
        {
            **_PERSON,
            "change_password": False,
            "auth_password": "Passw0rd1",
            **fields,
        }
    )


def _user(**fields: object) -> BaseModel:
    return UserRequest.model_validate({**_PERSON, **fields})


PERSON_FORMS: dict[str, Callable[..., BaseModel]] = {
    "register": _register,
    "profile": _profile,
    "user": _user,
}


_UUID = "0198a3c4-0000-7000-8000-000000000001"
_SCHEDULE = "2030-05-01T10:00:00"


def performance_request(**fields: object) -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "schedule": _SCHEDULE,
            "location_id": _UUID,
            "ordinariumwork_id": _UUID,
            "choirjob_defaultfee": 0,
            "instrument_defaultfee": 0,
            "voice_defaultfee": 0,
            "setup": {},
            **fields,
        }
    )


def ordinariumwork_request(**fields: object) -> OrdinariumworkRequest:
    return OrdinariumworkRequest.model_validate(
        {
            "name": "Messe in C",
            "artist_id": _UUID,
            "setup": {"instruments": [], "voices": []},
            **fields,
        }
    )
