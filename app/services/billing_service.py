from typing import TYPE_CHECKING

from app.schemas.booking import (
    BillingExtracostOutput,
    BillingItemOutput,
    BillingOrgfeeOutput,
    BillingOutput,
    BillingPositionOutput,
    BillingTypeOutput,
    CastSetupItemOutput,
    PerformanceBillingResponse,
)
from app.services import performance_service
from app.services.booking_common import get_performance_or_404, to_short_output
from app.services.booking_status_service import user_booking_status
from app.services.cast_service import get_booked_cast

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.db.models.user import User
    from app.schemas.performance import PerformancePositionOutput


# Fixed business constants of the organ-fee billing tiers -- not
# user-editable Settings fields, same reasoning as
# Performance.instrument_defaultfee being a real column rather than config.
_INSTRUMENTS_ORGFEE_TIER1_THRESHOLD = 0


_INSTRUMENTS_ORGFEE_TIER1 = 30


_INSTRUMENTS_ORGFEE_TIER2_THRESHOLD = 12


_INSTRUMENTS_ORGFEE_TIER2 = 55


_CHOIRJOBS_ORGFEE_THRESHOLD = 0


_CHOIRJOBS_ORGFEE = 15


def _billing_by_item(
    setup_item: PerformancePositionOutput,
    cast_item: CastSetupItemOutput,
    default_fee: int,
) -> BillingItemOutput:
    positions: list[BillingPositionOutput] = []
    total = 0
    for index in range(setup_item.quantity):
        if index < len(cast_item.cast):
            member = cast_item.cast[index]
            positions.append(
                BillingPositionOutput(id=member.id, name=member.name, fee=member.fee)
            )
            total += member.fee
        else:
            positions.append(
                BillingPositionOutput(id=None, name="N. N.", fee=default_fee)
            )
            total += default_fee
    return BillingItemOutput(
        id=setup_item.id,
        name=setup_item.name,
        quantity=setup_item.quantity,
        positions=positions,
        sum=total,
    )


def _billing_by_type(
    setup_items: list[PerformancePositionOutput],
    cast_items: list[CastSetupItemOutput],
    default_fee: int,
) -> BillingTypeOutput:
    cast_by_id = {item.id: item for item in cast_items}
    items: list[BillingItemOutput] = []
    total_sum = 0
    total_count = 0
    for setup_item in setup_items:
        billed = _billing_by_item(setup_item, cast_by_id[setup_item.id], default_fee)
        items.append(billed)
        total_sum += billed.sum
        total_count += billed.quantity
    return BillingTypeOutput(items=items, sum=total_sum, count=total_count)


def _org_fee(instrument_count: int, choirjob_count: int) -> BillingOrgfeeOutput:
    instruments_fee = 0
    if instrument_count > _INSTRUMENTS_ORGFEE_TIER1_THRESHOLD:
        instruments_fee = _INSTRUMENTS_ORGFEE_TIER1
    if instrument_count > _INSTRUMENTS_ORGFEE_TIER2_THRESHOLD:
        instruments_fee = _INSTRUMENTS_ORGFEE_TIER2  # replaces, not adds to, tier 1

    choirjobs_fee = 0
    if choirjob_count > _CHOIRJOBS_ORGFEE_THRESHOLD:
        choirjobs_fee = _CHOIRJOBS_ORGFEE

    return BillingOrgfeeOutput(
        instruments=instruments_fee,
        choirjobs=choirjobs_fee,
        sum=instruments_fee + choirjobs_fee,
    )


def get_billing(
    db: Session, performance_id: uuid.UUID, current_user: User
) -> PerformanceBillingResponse:
    """No past-lock -- the `billing` permission checks only the `billing`
    role, unlike `cast`/`maintain`."""
    performance = get_performance_or_404(db, performance_id)
    detail = performance_service.get_performance_detail(db, performance_id)
    setup = detail.setup
    booked_cast = get_booked_cast(db, performance, setup)

    instruments_bill = _billing_by_type(
        setup.instruments, booked_cast.instruments, performance.instrument_defaultfee
    )
    voices_bill = _billing_by_type(
        setup.voices, booked_cast.voices, performance.voice_defaultfee
    )
    choirjobs_bill = _billing_by_type(
        setup.choirjobs, booked_cast.choirjobs, performance.choirjob_defaultfee
    )
    orgfee = _org_fee(instruments_bill.count, choirjobs_bill.count)
    extracost = BillingExtracostOutput(
        amount=performance.extracost_amount or 0,
        description=performance.extracost_description or "",
    )
    total = (
        instruments_bill.sum
        + voices_bill.sum
        + choirjobs_bill.sum
        + orgfee.sum
        + extracost.amount
    )

    user_booking = user_booking_status(db, performance, current_user.id)
    short = to_short_output(detail, user_booking)
    return PerformanceBillingResponse(
        **short.model_dump(),
        billing=BillingOutput(
            instruments=instruments_bill,
            voices=voices_bill,
            choirjobs=choirjobs_bill,
            orgfee=orgfee,
            extracost=extracost,
            sum=total,
        ),
    )
