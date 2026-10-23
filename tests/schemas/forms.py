"""Valid request bodies of the forms that carry a person's name and phone
number, for tests that vary one field at a time."""

from typing import TYPE_CHECKING

from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleLinkRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
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
            "password": "Passw0rd12",
            "password_confirmation": "Passw0rd12",
            **fields,
        }
    )


def _profile(**fields: object) -> BaseModel:
    return ProfileUpdateRequest.model_validate(
        {
            **_PERSON,
            "change_password": False,
            "auth_password": "Passw0rd12",
            **fields,
        }
    )


def _user(**fields: object) -> BaseModel:
    return UserRequest.model_validate({**_PERSON, **fields})


def _forgot_password(**fields: object) -> BaseModel:
    return ForgotPasswordRequest.model_validate({"email": _PERSON["email"], **fields})


def _reset_password(**fields: object) -> BaseModel:
    return ResetPasswordRequest.model_validate(
        {
            "email": _PERSON["email"],
            "token": "token",
            "password": "Passw0rd12",
            "password_confirmation": "Passw0rd12",
            **fields,
        }
    )


def _google_link(**fields: object) -> BaseModel:
    return GoogleLinkRequest.model_validate(
        {
            "credential": "credential",
            "email": _PERSON["email"],
            "password": "Passw0rd12",
            **fields,
        }
    )


# Every form that takes an e-mail address.
EMAIL_FORMS: dict[str, Callable[..., BaseModel]] = {
    "register": _register,
    "profile": _profile,
    "user": _user,
    "forgot_password": _forgot_password,
    "reset_password": _reset_password,
    "google_link": _google_link,
}

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
