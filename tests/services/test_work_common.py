import uuid
from typing import TYPE_CHECKING

import pytest

from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.propriumwork import Propriumwork
from app.schemas.artist import ArtistRequest
from app.schemas.ordinariumwork import OrdinariumworkResponse
from app.schemas.propriumwork import PropriumworkResponse
from app.services import artist_service, ordinariumwork_service, propriumwork_service
from app.services.work_common import (
    WorkKind,
    search_works,
    validate_work_fields,
    work_response,
)
from tests.sql_capture import recorded_statements

if TYPE_CHECKING:
    from pydantic import BaseModel
    from sqlalchemy.orm import Session

ORDINARIUMWORK = WorkKind(model=Ordinariumwork, response_type=OrdinariumworkResponse)
PROPRIUMWORK = WorkKind(model=Propriumwork, response_type=PropriumworkResponse)

KINDS = [
    pytest.param(ORDINARIUMWORK, id="ordinariumwork"),
    pytest.param(PROPRIUMWORK, id="propriumwork"),
]

OTHER_KIND = {Ordinariumwork: PROPRIUMWORK, Propriumwork: ORDINARIUMWORK}


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_artist(
    db_session: Session, surname: str | None = None, givenname: str = "Given"
) -> uuid.UUID:
    artist = artist_service.create_artist(
        db_session,
        ArtistRequest(
            surname=surname or _unique("Composer"), givenname=givenname, composer=True
        ),
    )
    return artist.id


def _make_work(
    db_session: Session,
    kind: WorkKind[BaseModel],
    artist_id: uuid.UUID,
    name: str,
    *,
    duration: int | None = None,
) -> uuid.UUID:
    work = kind.model(
        name=name,
        description=None,
        artist_id=artist_id,
        duration=duration,
        demanding=False,
    )
    db_session.add(work)
    db_session.commit()
    return work.id


def _validate(
    db_session: Session,
    kind: WorkKind[BaseModel],
    artist_id: uuid.UUID,
    **overrides: object,
):
    fields: dict[str, object] = {
        "name": _unique("Werk"),
        "artist_id": artist_id,
        "duration": None,
        "exclude_id": None,
    }
    fields.update(overrides)
    return validate_work_fields(db_session, kind, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", KINDS)
class TestKindsAreWiredToTheirOwnService:
    def test_both_services_use_their_own_table(self, kind: WorkKind[BaseModel]):
        wired = {
            Ordinariumwork: ordinariumwork_service._WORK_KIND,
            Propriumwork: propriumwork_service._WORK_KIND,
        }

        assert wired[kind.model] == kind


@pytest.mark.parametrize("kind", KINDS)
class TestValidateWorkFields:
    def test_accepts_valid_fields(self, db_session: Session, kind: WorkKind[BaseModel]):
        artist_id = _make_artist(db_session)

        assert _validate(db_session, kind, artist_id, duration=45) == []

    @pytest.mark.parametrize(
        ("name", "valid"),
        [("ab", False), ("abc", True), ("x" * 60, True), ("x" * 61, False)],
    )
    def test_name_length_is_bounded_to_three_to_sixty(
        self, db_session: Session, kind: WorkKind[BaseModel], name: str, valid: bool
    ):
        artist_id = _make_artist(db_session)

        errors = _validate(db_session, kind, artist_id, name=name)

        assert errors == (
            [] if valid else [("name", "Muss zwischen 3 und 60 Zeichen lang sein.")]
        )

    def test_rejects_an_unknown_artist(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        errors = _validate(db_session, kind, uuid.uuid4())

        assert errors == [("artist_id", "Komponist/in wurde nicht gefunden.")]

    @pytest.mark.parametrize(
        ("duration", "valid"),
        [(None, True), (0, False), (1, True), (999, True), (1000, False)],
    )
    def test_duration_is_bounded_to_one_to_999_minutes(
        self,
        db_session: Session,
        kind: WorkKind[BaseModel],
        duration: int | None,
        valid: bool,
    ):
        artist_id = _make_artist(db_session)

        errors = _validate(db_session, kind, artist_id, duration=duration)

        assert errors == (
            [] if valid else [("duration", "Muss zwischen 1 und 999 liegen.")]
        )

    def test_rejects_the_same_name_of_the_same_artist_in_any_letter_case(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        artist_id = _make_artist(db_session)
        _make_work(db_session, kind, artist_id, "Ave Maria")

        errors = _validate(db_session, kind, artist_id, name="AVE maria")

        assert errors == [
            ("name", "Dieses Werk ist für diesen Komponisten bereits erfasst.")
        ]

    def test_allows_the_same_name_for_another_artist(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        first_artist_id, second_artist_id = (
            _make_artist(db_session),
            _make_artist(db_session),
        )
        _make_work(db_session, kind, first_artist_id, "Ave Maria")

        assert _validate(db_session, kind, second_artist_id, name="Ave Maria") == []

    def test_the_work_being_updated_does_not_clash_with_itself(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        artist_id = _make_artist(db_session)
        own_id = _make_work(db_session, kind, artist_id, "Ave Maria")

        assert (
            _validate(db_session, kind, artist_id, name="Ave Maria", exclude_id=own_id)
            == []
        )

    def test_excluding_one_work_still_finds_a_clash_with_another(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        artist_id = _make_artist(db_session)
        _make_work(db_session, kind, artist_id, "Ave Maria")

        errors = _validate(
            db_session, kind, artist_id, name="Ave Maria", exclude_id=uuid.uuid4()
        )

        assert errors == [
            ("name", "Dieses Werk ist für diesen Komponisten bereits erfasst.")
        ]

    def test_a_name_used_in_the_other_work_table_is_no_clash(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        artist_id = _make_artist(db_session)
        _make_work(db_session, OTHER_KIND[kind.model], artist_id, "Ave Maria")

        assert _validate(db_session, kind, artist_id, name="Ave Maria") == []

    def test_reports_every_failing_field_in_field_order(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        errors = _validate(db_session, kind, uuid.uuid4(), name="ab", duration=0)

        assert [field for field, _message in errors] == [
            "name",
            "artist_id",
            "duration",
        ]

    def test_costs_two_queries(
        self, db_session: Session, kind: WorkKind[BaseModel], count_queries
    ):
        artist_id = _make_artist(db_session)

        with count_queries() as counter:
            _validate(db_session, kind, artist_id)

        assert counter.count == 2


@pytest.mark.parametrize("kind", KINDS)
class TestSearchWorks:
    def test_blank_query_finds_nothing_and_asks_nothing(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        with recorded_statements() as statements:
            assert search_works(db_session, kind, "  ") == []

        assert statements == []

    @pytest.mark.parametrize("wildcard", ["%", "_", "\\"])
    def test_wildcard_characters_match_only_literally(
        self, db_session: Session, kind: WorkKind[BaseModel], wildcard: str
    ):
        _make_work(db_session, kind, _make_artist(db_session), _unique("Introitus"))

        assert search_works(db_session, kind, wildcard) == []

    def test_an_underscore_finds_a_name_that_contains_one(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        name = _unique("Intro_itus")
        work_id = _make_work(db_session, kind, _make_artist(db_session), name)

        results = search_works(db_session, kind, "intro_i")

        assert [result.id for result in results] == [work_id]

    def test_every_word_must_match_the_artist_or_the_work_name(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        marker = uuid.uuid4().hex[:8]
        haydn_id = _make_artist(db_session, f"Haydn{marker}", "Joseph")
        mozart_id = _make_artist(db_session, f"Mozart{marker}", "Wolfgang")
        wanted_id = _make_work(db_session, kind, haydn_id, f"Graduale {marker}")
        _make_work(db_session, kind, mozart_id, f"Graduale {marker}")
        _make_work(db_session, kind, haydn_id, f"Offertorium {marker}")

        results = search_works(db_session, kind, f"haydn{marker} graduale")

        assert [result.id for result in results] == [wanted_id]

    def test_labels_the_work_with_its_artist(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        marker = uuid.uuid4().hex[:8]
        artist_id = _make_artist(db_session, f"Haydn{marker}", "Joseph")
        _make_work(db_session, kind, artist_id, f"Graduale {marker}")

        results = search_works(db_session, kind, marker)

        assert [result.label for result in results] == [
            f"HAYDN{marker.upper()}, Joseph: Graduale {marker}"
        ]

    def test_sorts_by_artist_surname_then_work_name(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        marker = uuid.uuid4().hex[:8]
        bach_id = _make_artist(db_session, f"Bach{marker}")
        alt_id = _make_artist(db_session, f"Alt{marker}")
        second = _make_work(db_session, kind, bach_id, f"B {marker}")
        first = _make_work(db_session, kind, bach_id, f"A {marker}")
        zeroth = _make_work(db_session, kind, alt_id, f"Z {marker}")

        results = search_works(db_session, kind, marker)

        assert [result.id for result in results] == [zeroth, first, second]

    def test_returns_at_most_twenty_results(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        marker = uuid.uuid4().hex[:8]
        artist_id = _make_artist(db_session)
        for number in range(21):
            _make_work(db_session, kind, artist_id, f"Werk {number:02d} {marker}")

        assert len(search_works(db_session, kind, marker)) == 20

    def test_does_not_return_works_of_the_other_table(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        marker = uuid.uuid4().hex[:8]
        other = OTHER_KIND[kind.model]
        _make_work(db_session, other, _make_artist(db_session), f"Graduale {marker}")

        assert search_works(db_session, kind, marker) == []

    def test_costs_one_query(
        self, db_session: Session, kind: WorkKind[BaseModel], count_queries
    ):
        marker = uuid.uuid4().hex[:8]
        artist_id = _make_artist(db_session)
        for number in range(3):
            _make_work(db_session, kind, artist_id, f"Werk {number} {marker}")

        with count_queries() as counter:
            search_works(db_session, kind, marker)

        assert counter.count == 1


@pytest.mark.parametrize("kind", KINDS)
class TestWorkResponse:
    def test_maps_every_field_and_labels_the_artist(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        artist_id = _make_artist(db_session, "Haydn", "Joseph")
        work = kind.model(
            name="Graduale",
            description="Beschreibung",
            artist_id=artist_id,
            duration=7,
            demanding=True,
        )
        db_session.add(work)
        db_session.commit()

        response = work_response(db_session, kind, work)

        assert isinstance(response, kind.response_type)
        assert response.model_dump() == {
            "id": work.id,
            "name": "Graduale",
            "description": "Beschreibung",
            "artist_id": artist_id,
            "artist_name": "HAYDN, Joseph",
            "duration": 7,
            "demanding": True,
        }

    def test_an_unknown_artist_gives_an_empty_artist_name(
        self, db_session: Session, kind: WorkKind[BaseModel]
    ):
        work = kind.model(
            id=uuid.uuid4(),
            name="Graduale",
            description=None,
            artist_id=uuid.uuid4(),
            duration=None,
            demanding=False,
        )

        assert work_response(db_session, kind, work).model_dump()["artist_name"] == ""

    def test_costs_one_query(
        self, db_session: Session, kind: WorkKind[BaseModel], count_queries
    ):
        work_id = _make_work(db_session, kind, _make_artist(db_session), "Graduale")
        work = db_session.get(kind.model, work_id)

        with count_queries() as counter:
            work_response(db_session, kind, work)

        assert counter.count == 1
