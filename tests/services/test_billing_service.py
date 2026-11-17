from typing import TYPE_CHECKING

import pytest

from app.services import billing_service, cast_service
from app.services.booking_common import display_name
from tests.booking_helpers import (
    create_choirjob,
    create_instrument,
    create_performance,
    create_voice,
    move_to_past,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestGetBilling:
    def test_billing_sums_booked_and_unfilled_slots(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 2})
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )
        current_user = make_user()

        billing = billing_service.get_billing(db_session, performance_id, current_user)

        assert (
            billing.billing.instruments.items[0].sum == 80 + 60
        )  # booked + default fee slot
        assert billing.billing.instruments.count == 2

    def test_every_part_of_the_bill_is_summed_from_its_own_source(
        self, db_session: Session, make_user
    ):
        # Every amount differs from all others, so a swapped default fee, a
        # dropped summand or a wrong organisation-fee input changes the total.
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        choirjob = create_choirjob(db_session)
        performance_id = create_performance(
            db_session,
            instruments={instrument.id: 2},
            voices={voice.id: 1},
            choirjobs={choirjob.id: 2},
            extracost_amount=25,
            extracost_description="Parking",
        )
        instrument_singer = make_user()
        choirjob_member = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(instrument_singer.id, 80)],
            old_quantity=None,
        )
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "choirjobs",
            choirjob.id,
            new_cast=[(choirjob_member.id, 20)],
            old_quantity=None,
        )

        bill = billing_service.get_billing(
            db_session, performance_id, make_user()
        ).billing

        assert [(p.id, p.name, p.fee) for p in bill.instruments.items[0].positions] == [
            (instrument_singer.id, display_name(instrument_singer), 80),
            (None, "N. N.", 60),
        ]
        assert [(p.id, p.name, p.fee) for p in bill.voices.items[0].positions] == [
            (None, "N. N.", 110)
        ]
        assert [(p.id, p.name, p.fee) for p in bill.choirjobs.items[0].positions] == [
            (choirjob_member.id, display_name(choirjob_member), 20),
            (None, "N. N.", 35),
        ]
        assert (bill.instruments.sum, bill.instruments.count) == (140, 2)
        assert (bill.voices.sum, bill.voices.count) == (110, 1)
        assert (bill.choirjobs.sum, bill.choirjobs.count) == (55, 2)
        assert (bill.orgfee.instruments, bill.orgfee.choirjobs, bill.orgfee.sum) == (
            30,
            15,
            45,
        )
        assert (bill.extracost.amount, bill.extracost.description) == (25, "Parking")
        assert bill.sum == 140 + 110 + 55 + 45 + 25

    @pytest.mark.parametrize(
        ("instrument_count", "expected_fee"),
        [(0, 0), (1, 30), (12, 30), (13, 55)],
    )
    def test_instruments_orgfee_thresholds(self, instrument_count, expected_fee):
        orgfee = billing_service._org_fee(instrument_count, 0)
        assert orgfee.instruments == expected_fee

    @pytest.mark.parametrize(("choirjob_count", "expected_fee"), [(0, 0), (1, 15)])
    def test_choirjobs_orgfee_thresholds(self, choirjob_count, expected_fee):
        orgfee = billing_service._org_fee(0, choirjob_count)
        assert orgfee.choirjobs == expected_fee

    def test_billing_has_no_past_lock(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        current_user = make_user()

        billing = billing_service.get_billing(db_session, performance_id, current_user)

        # Not locked although the performance lies in the past: one unfilled
        # instrument slot at the default fee (60) plus the organisation fee
        # for one instrument (30).
        assert billing.billing.instruments.count == 1
        assert billing.billing.sum == 60 + 30
