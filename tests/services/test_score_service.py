import uuid
from datetime import UTC, datetime
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
    def test_required_numbers_default_to_zero(self):
        defaults = score_service.get_defaults()
        assert defaults["violine1"] == 0

    def test_geboren_gestorben_jahr_default_to_none(self):
        defaults = score_service.get_defaults()
        assert defaults["geboren"] is None
        assert defaults["gestorben"] is None
        assert defaults["jahr"] is None

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

    @pytest.mark.parametrize("wildcard", ["%", "_", "\\"])
    def test_wildcard_characters_match_only_literally(
        self, db_session: Session, wildcard: str
    ):
        score_service.create_score(
            db_session, _payload(surname="Haydn", givenname="Joseph", werk=_unique())
        )

        assert score_service.search_scores(db_session, wildcard) == []

    def test_an_underscore_finds_a_title_that_contains_one(self, db_session: Session):
        marker = _unique("Wer_k")
        score_service.create_score(
            db_session, _payload(surname="Haydn", givenname="Joseph", werk=marker)
        )

        results = score_service.search_scores(db_session, "wer_k")

        assert [marker in result.label for result in results] == [True]

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


class TestSearchLabelDisambiguation:
    """Several versions of one work are normal in the archive, so hits that
    would read identically get just enough of verz, box, year, genre (or the
    entry date) to be told apart; every other hit keeps its plain label."""

    def _cards(self, db_session: Session, marker: str, *variants: dict[str, object]):
        return [
            score_service.create_score(
                db_session,
                _payload(
                    werk=marker, surname="Mozart", givenname="Wolfgang", **variant
                ),
            )
            for variant in variants
        ]

    def _labels(self, db_session: Session, marker: str) -> list[str]:
        return [
            result.label
            for result in score_service.search_scores(db_session, marker.lower())
        ]

    def test_catalogue_number_tells_versions_apart(self, db_session: Session):
        marker = _unique("Sonate")
        self._cards(db_session, marker, {"verz": "KV 263"}, {"verz": "KV 336"})

        labels = self._labels(db_session, marker)

        assert labels == [
            f"MOZART, Wolfgang: {marker} - KV 263",
            f"MOZART, Wolfgang: {marker} - KV 336",
        ]

    def test_box_is_used_when_the_catalogue_number_does_not_differ(
        self, db_session: Session
    ):
        marker = _unique("Pueri")
        self._cards(db_session, marker, {"boxnr": "A2.07"}, {"boxnr": "10.02"})

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker} - Box 10.02",
            f"MOZART, Wolfgang: {marker} - Box A2.07",
        ]

    def test_year_is_used_when_catalogue_number_and_box_are_equal(
        self, db_session: Session
    ):
        marker = _unique("Christus")
        self._cards(db_session, marker, {"jahr": 1884}, {"jahr": 1873})

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker} - 1873",
            f"MOZART, Wolfgang: {marker} - 1884",
        ]

    def test_genre_is_the_last_field_tried(self, db_session: Session):
        marker = _unique("Martin")
        self._cards(
            db_session, marker, {"sparte": "Lied"}, {"sparte": "Advent/Weihnacht"}
        )

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker} - Advent/Weihnacht",
            f"MOZART, Wolfgang: {marker} - Lied",
        ]

    def test_a_field_that_does_not_differ_is_left_out(self, db_session: Session):
        marker = _unique("Gleich")
        self._cards(
            db_session,
            marker,
            {"verz": "KV 1", "boxnr": "1"},
            {"verz": "KV 1", "boxnr": "2"},
        )

        labels = self._labels(db_session, marker)

        assert labels == [
            f"MOZART, Wolfgang: {marker} - Box 1",
            f"MOZART, Wolfgang: {marker} - Box 2",
        ]

    def test_fields_are_added_until_every_card_is_unique(self, db_session: Session):
        marker = _unique("Mehrfach")
        self._cards(
            db_session,
            marker,
            {"verz": "KV 1", "boxnr": "1"},
            {"verz": "KV 1", "boxnr": "2"},
            {"verz": "KV 2", "boxnr": "1"},
        )

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker} - KV 1, Box 1",
            f"MOZART, Wolfgang: {marker} - KV 1, Box 2",
            f"MOZART, Wolfgang: {marker} - KV 2, Box 1",
        ]

    def test_a_card_without_the_field_keeps_the_plain_label(self, db_session: Session):
        marker = _unique("Teils")
        self._cards(db_session, marker, {"verz": "KV 329"}, {"verz": ""})

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker}",
            f"MOZART, Wolfgang: {marker} - KV 329",
        ]

    def test_entry_date_is_the_last_resort(self, db_session: Session):
        marker = _unique("Datum")
        first, second = self._cards(db_session, marker, {}, {})
        for created, when in (
            (first, datetime(2020, 1, 2, tzinfo=UTC)),
            (second, datetime(2021, 8, 4, tzinfo=UTC)),
        ):
            db_session.query(Score).filter(Score.id == created.id).update(
                {Score.created_at: when}
            )
        db_session.commit()

        labels = self._labels(db_session, marker)

        assert sorted(labels) == [
            f"MOZART, Wolfgang: {marker} - erfasst am 02.01.2020",
            f"MOZART, Wolfgang: {marker} - erfasst am 04.08.2021",
        ]

    def test_cards_that_cannot_be_told_apart_keep_the_plain_label(
        self, db_session: Session
    ):
        marker = _unique("Identisch")
        first, second = self._cards(db_session, marker, {}, {})
        db_session.query(Score).filter(Score.id.in_([first.id, second.id])).update(
            {Score.created_at: datetime(2020, 1, 2, tzinfo=UTC)}
        )
        db_session.commit()

        labels = self._labels(db_session, marker)

        assert labels == [f"MOZART, Wolfgang: {marker}"] * 2

    def test_hits_without_a_clash_are_untouched(self, db_session: Session):
        marker = _unique("Einzeln")
        other_marker = f"{marker} anderes"
        self._cards(db_session, marker, {"verz": "KV 1"}, {"verz": "KV 2"})
        score_service.create_score(
            db_session,
            _payload(
                werk=other_marker, surname="Mozart", givenname="Wolfgang", verz="KV 9"
            ),
        )

        labels = self._labels(db_session, marker)

        assert f"MOZART, Wolfgang: {other_marker}" in labels
        assert f"MOZART, Wolfgang: {marker} - KV 1" in labels

    def test_hits_of_one_composer_are_ordered_by_work_then_part(
        self, db_session: Session
    ):
        marker = _unique("Ordnung")
        score_service.create_score(
            db_session, _payload(werk=f"{marker} Z", surname="Mozart")
        )
        score_service.create_score(
            db_session, _payload(werk=f"{marker} A", surname="Mozart")
        )

        labels = self._labels(db_session, marker)

        assert [label.split(": ")[1] for label in labels] == [
            f"{marker} A",
            f"{marker} Z",
        ]

    def test_search_costs_one_statement_however_many_hits_clash(
        self, db_session: Session, count_queries
    ):
        marker = _unique("Zaehler")
        self._cards(
            db_session, marker, *({"verz": f"KV {number}"} for number in range(6))
        )

        with count_queries() as counter:
            score_service.search_scores(db_session, marker.lower())

        assert counter.count == 1


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

    def test_the_same_work_can_be_stored_as_several_cards(self, db_session: Session):
        werk = _unique()
        first = score_service.create_score(
            db_session,
            _payload(werk=werk, surname="Haydn", givenname="Joseph", teil=""),
        )
        second = score_service.create_score(
            db_session,
            _payload(werk=werk, surname="Haydn", givenname="Joseph", teil=""),
        )

        assert first.id != second.id
        assert first.fields["werk"] == second.fields["werk"] == werk

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


class TestOptionalYearFields:
    def test_left_blank_they_are_stored_and_read_back_as_none(
        self, db_session: Session
    ):
        created = score_service.create_score(db_session, _payload())
        score = db_session.get(Score, created.id)
        assert score is not None
        assert score.geboren is None
        assert score.gestorben is None
        assert score.jahr is None
        assert created.fields["geboren"] is None
        assert created.fields["gestorben"] is None
        assert created.fields["jahr"] is None

    def test_a_real_year_is_kept_as_is(self, db_session: Session):
        created = score_service.create_score(
            db_session, _payload(geboren=1756, gestorben=1791, jahr=1787)
        )
        assert created.fields["geboren"] == 1756
        assert created.fields["gestorben"] == 1791
        assert created.fields["jahr"] == 1787

    def test_blank_string_from_a_number_input_is_normalized_to_none(self):
        # The form's <input type="number"> submits "" when left blank, not
        # null (Vue's v-model.number modifier passes an empty field through
        # as a string) -- same BlankToNone normalization text fields get.
        payload = _payload(geboren="", jahr="")
        assert payload.geboren is None
        assert payload.jahr is None

    def test_out_of_range_year_is_rejected(self):
        with pytest.raises(ValidationError):
            _payload(jahr=10000)


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

    def test_a_card_with_identical_siblings_can_be_edited(self, db_session: Session):
        werk = _unique()
        sibling_ids = [
            score_service.create_score(
                db_session,
                _payload(werk=werk, surname="Mozart", givenname="Wolfgang Amadeus"),
            ).id
            for _ in range(2)
        ]

        updated = score_service.update_score(
            db_session,
            sibling_ids[0],
            _payload(
                werk=werk,
                surname="Mozart",
                givenname="Wolfgang Amadeus",
                bemerkung="Box gewechselt",
            ),
        )

        assert updated.id == sibling_ids[0]
        assert updated.fields["bemerkung"] == "Box gewechselt"
        untouched = score_service.get_score(db_session, sibling_ids[1])
        assert untouched.fields["bemerkung"] != "Box gewechselt"

    def test_a_card_can_take_over_the_identity_of_another_card(
        self, db_session: Session
    ):
        werk = _unique()
        other = score_service.create_score(
            db_session, _payload(werk=werk, surname="Haydn", givenname="Joseph")
        )
        score = score_service.create_score(db_session, _payload())

        updated = score_service.update_score(
            db_session,
            score.id,
            _payload(werk=werk, surname="Haydn", givenname="Joseph"),
        )

        assert updated.id == score.id != other.id
        assert updated.fields["werk"] == other.fields["werk"] == werk


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
