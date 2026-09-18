import uuid
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.db.models.score import Score
from app.schemas.score import ScoreRequest
from app.services import score_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _unique(base: str = "Werk") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _payload(**overrides: object) -> ScoreRequest:
    data: dict[str, object] = {
        **score_service.get_defaults(),
        "kasten": "A",
        "boxnr": "1",
        "inhalt": "Partitur",
        "werk": _unique(),
        **overrides,
    }
    return ScoreRequest(**data)  # type: ignore[arg-type]


class TestGetFieldsConfig:
    def test_covers_every_score_field(self):
        config = score_service.get_fields_config()
        assert len(config) == 94

    def test_only_orch_has_no_anz_field(self):
        # Regression test: "orgel" has an "anz" column (the Show page
        # displays an Orgel-Stimme "Anzahl" cell), only "orch" lacks one.
        config = score_service.get_fields_config()
        assert "orgelanz" in config
        assert "orchanz" not in config

    def test_required_text_field_reports_its_length(self):
        config = score_service.get_fields_config()
        assert config["kasten"].required is True
        assert config["kasten"].length == 2

    def test_select_field_reports_its_values(self):
        config = score_service.get_fields_config()
        assert config["inhalt"].values is not None
        assert "Partitur" in config["inhalt"].values

    def test_required_select_offers_no_blank_option(self):
        config = score_service.get_fields_config()
        assert config["inhalt"].required is True
        assert config["inhalt"].values is not None
        assert "" not in config["inhalt"].values

    def test_optional_selects_keep_their_blank_option(self):
        config = score_service.get_fields_config()
        for name in ("sparte", "part1art", "orchart"):
            assert config[name].required is False
            assert config[name].values is not None
            assert config[name].values[0] == ""


class TestGetDefaults:
    def test_numbers_default_to_zero(self):
        defaults = score_service.get_defaults()
        assert defaults["violine1"] == 0
        assert defaults["geboren"] == 0

    def test_text_defaults_to_empty_string(self):
        defaults = score_service.get_defaults()
        assert defaults["kasten"] == ""

    def test_selects_default_to_the_blank_state(self):
        defaults = score_service.get_defaults()
        assert defaults["inhalt"] == ""
        assert defaults["sparte"] == ""


class TestSearchScores:
    def test_blank_query_returns_no_results(self, db_session: Session):
        assert score_service.search_scores(db_session, "   ") == []

    def test_finds_by_composer_surname_and_givenname(self, db_session: Session):
        marker = _unique("Mozartsuche")
        score_service.create_score(
            db_session, _payload(surname="Mozart", givenname="Wolfgang", werk=marker)
        )
        results = score_service.search_scores(db_session, "mozart wolfgang")
        assert marker in [r.label.split(": ")[1] for r in results]

    def test_every_word_must_match(self, db_session: Session):
        marker = _unique("Wortsuche")
        score_service.create_score(
            db_session, _payload(surname="Haydn", givenname="Joseph", werk=marker)
        )
        assert (
            score_service.search_scores(db_session, f"haydn {marker} nonexistentword")
            == []
        )

    def test_treats_missing_teil_as_searchable_empty(self, db_session: Session):
        marker = _unique("Ohneteil")
        score_service.create_score(
            db_session,
            _payload(surname="Bach", givenname="Johann", werk=marker, teil=""),
        )
        results = score_service.search_scores(db_session, marker.lower())
        assert any(marker in r.label for r in results)

    def test_label_includes_teil_when_present(self, db_session: Session):
        marker = _unique("Mitteil")
        created = score_service.create_score(
            db_session,
            _payload(surname="Bach", givenname="Johann", werk=marker, teil="Kyrie"),
        )
        results = score_service.search_scores(db_session, marker.lower())
        result = next(r for r in results if r.id == created.id)
        assert result.label.endswith(" / Kyrie")

    def test_sorted_by_surname(self, db_session: Session):
        shared_werk_word = _unique("Sortierwerk")
        surname_a, surname_z = _unique("AAA"), _unique("ZZZ")
        score_service.create_score(
            db_session, _payload(surname=surname_z, werk=f"{shared_werk_word} Z")
        )
        score_service.create_score(
            db_session, _payload(surname=surname_a, werk=f"{shared_werk_word} A")
        )
        results = score_service.search_scores(db_session, shared_werk_word.lower())
        # normalize_surname() uppercases on save, so the label carries the
        # uppercased surname, not the mixed-case value this test passed in.
        surnames = [r.label for r in results]
        assert surnames.index(
            next(s for s in surnames if surname_a.upper() in s)
        ) < surnames.index(next(s for s in surnames if surname_z.upper() in s))


class TestCreateScore:
    def test_creates_with_given_fields(self, db_session: Session):
        werk = _unique()
        result = score_service.create_score(
            db_session, _payload(werk=werk, bemerkung="Testnotiz")
        )
        assert result.fields["werk"] == werk
        assert result.fields["bemerkung"] == "Testnotiz"
        assert result.fields["kasten"] == "A"

    def test_normalizes_surname_and_givenname(self, db_session: Session):
        result = score_service.create_score(
            db_session, _payload(surname="mozart", givenname="wolfgang amadé")
        )
        assert result.fields["surname"] == "MOZART"
        assert result.fields["givenname"] == "Wolfgang Amadé"

    def test_duplicate_werk_within_same_composer_and_teil_is_rejected(
        self, db_session: Session
    ):
        werk = _unique()
        score_service.create_score(
            db_session,
            _payload(werk=werk, surname="Haydn", givenname="Joseph", teil=""),
        )
        with pytest.raises(score_service.ScoreValidationError) as exc_info:
            score_service.create_score(
                db_session,
                _payload(werk=werk, surname="Haydn", givenname="Joseph", teil=""),
            )
        assert exc_info.value.errors == [
            ("werk", "Name, Komponist und Werkteil müssen zusammen eindeutig sein")
        ]

    def test_same_werk_with_different_teil_is_allowed(self, db_session: Session):
        werk = _unique()
        score_service.create_score(
            db_session,
            _payload(werk=werk, surname="Haydn", givenname="Joseph", teil="Kyrie"),
        )
        result = score_service.create_score(
            db_session,
            _payload(werk=werk, surname="Haydn", givenname="Joseph", teil="Gloria"),
        )
        assert result.fields["teil"] == "Gloria"

    def test_same_werk_with_different_composer_is_allowed(self, db_session: Session):
        werk = _unique()
        score_service.create_score(
            db_session, _payload(werk=werk, surname="Haydn", givenname="Joseph")
        )
        result = score_service.create_score(
            db_session, _payload(werk=werk, surname="Mozart", givenname="Wolfgang")
        )
        assert result.fields["werk"] == werk


class TestBlankOptionalValues:
    def test_blank_optional_text_and_selects_are_stored_as_null(
        self, db_session: Session
    ):
        created = score_service.create_score(
            db_session, _payload(surname="Bach", teil="", sparte="", part1art="")
        )
        score = db_session.get(Score, created.id)
        assert score is not None
        assert score.teil is None
        assert score.sparte is None
        assert score.part1art is None
        assert score.auch is None

    def test_blank_optional_values_are_read_back_as_empty_strings(
        self, db_session: Session
    ):
        created = score_service.create_score(
            db_session, _payload(surname="Bach", teil="", sparte="")
        )
        assert created.fields["teil"] == ""
        assert created.fields["sparte"] == ""

    def test_whitespace_only_optional_text_counts_as_blank(self, db_session: Session):
        created = score_service.create_score(
            db_session, _payload(surname="Bach", bemerkung="   ")
        )
        score = db_session.get(Score, created.id)
        assert score is not None
        assert score.bemerkung is None

    def test_blank_composer_name_is_stored_as_null(self, db_session: Session):
        created = score_service.create_score(
            db_session, _payload(surname="", givenname="")
        )
        score = db_session.get(Score, created.id)
        assert score is not None
        assert score.surname is None
        assert score.givenname is None


class TestRequiredSelectRejectsBlank:
    def test_blank_inhalt_is_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            _payload(inhalt="")
        assert exc_info.value.errors()[0]["loc"] == ("inhalt",)

    def test_unknown_select_value_is_rejected(self):
        with pytest.raises(ValidationError):
            _payload(sparte="Bogus")


class TestUpdateScore:
    def test_updates_fields(self, db_session: Session):
        created = score_service.create_score(db_session, _payload())
        updated = score_service.update_score(
            db_session,
            created.id,
            _payload(werk=created.fields["werk"], bemerkung="Neu"),
        )
        assert updated.fields["bemerkung"] == "Neu"

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(score_service.ScoreNotFoundError):
            score_service.update_score(db_session, uuid.uuid4(), _payload())

    def test_keeping_own_werk_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        werk = _unique()
        created = score_service.create_score(db_session, _payload(werk=werk))
        updated = score_service.update_score(
            db_session, created.id, _payload(werk=werk, bemerkung="unverändert")
        )
        assert updated.fields["werk"] == werk

    def test_duplicate_werk_against_another_score_is_rejected(
        self, db_session: Session
    ):
        werk = _unique()
        other = score_service.create_score(
            db_session, _payload(werk=werk, surname="Haydn", givenname="Joseph")
        )
        score = score_service.create_score(db_session, _payload())
        with pytest.raises(score_service.ScoreValidationError) as exc_info:
            score_service.update_score(
                db_session,
                score.id,
                _payload(werk=werk, surname="Haydn", givenname="Joseph"),
            )
        assert exc_info.value.errors == [
            ("werk", "Name, Komponist und Werkteil müssen zusammen eindeutig sein")
        ]
        assert other.fields["werk"] == werk


class TestGetScore:
    def test_returns_all_field_values(self, db_session: Session):
        created = score_service.create_score(db_session, _payload())
        fetched = score_service.get_score(db_session, created.id)
        assert fetched.fields == created.fields

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(score_service.ScoreNotFoundError):
            score_service.get_score(db_session, uuid.uuid4())


def test_no_delete_function_exists():
    # Regression guard: an "archive" is never deleted -- this must stay
    # true.
    assert not hasattr(score_service, "delete_score")
