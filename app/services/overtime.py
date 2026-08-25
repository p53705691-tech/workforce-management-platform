"""Overtime tiering: pure business logic, no DB access, no I/O.

Deliberately separated from ``app.services.working_hours`` (which does
the DB work of summing worked seconds) so the tiering arithmetic —
the actual crux of this milestone — can be unit-tested in complete
isolation, with no database or Flask app context required.

Confirmed business rules (do not re-litigate):

- Daily OT: the first 2 hours beyond the daily threshold are paid at
  1.5x; daily OT beyond that (hour 3+ of daily OT) is paid at 2.0x.
- Weekly OT: hours beyond the weekly threshold are paid at 1.5x, but
  only hours not already counted as daily OT for that week (no
  double-counting the same worked hour under two multipliers).
- Thresholds and multipliers are configurable data (``OvertimePolicy``
  and ``OvertimeTier`` rows), never hardcoded constants — this module
  only knows how to apply whatever tiers it is given.
- No proration of the weekly threshold for a partial week.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from app.extensions import db
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier


@dataclass(frozen=True)
class TierSpec:
    """One multiplier tier, in hours beyond the relevant threshold."""

    from_hours: Decimal
    to_hours: Decimal | None
    multiplier: Decimal


@dataclass(frozen=True)
class PaidBucket:
    """A slice of hours paid at a single multiplier."""

    hours: Decimal
    multiplier: Decimal


@dataclass(frozen=True)
class ResolvedPolicy:
    """The effective policy + tiers for an organization on a given date,
    converted into the plain ``TierSpec`` shape the pure functions below
    consume — decouples them from the ORM models entirely.
    """

    policy_id: int
    daily_threshold_hours: Decimal
    weekly_threshold_hours: Decimal
    week_start_day: int
    daily_tiers: list[TierSpec]
    weekly_tiers: list[TierSpec]


def apply_tiers(hours: Decimal, tiers: list[TierSpec]) -> list[PaidBucket]:
    """Split ``hours`` (already beyond whatever threshold applies) into
    buckets per tier boundary.

    Tiers are matched by ``from_hours``/``to_hours`` regardless of the
    order they're passed in (sorted here), since a tier's own row order
    in the database is not a safe assumption to make about a caller's
    list. A ``None`` ``to_hours`` means "unbounded" — it absorbs
    whatever of ``hours`` remains above its ``from_hours``.
    """
    if hours <= 0:
        return []

    buckets: list[PaidBucket] = []
    for tier in sorted(tiers, key=lambda t: t.from_hours):
        if hours <= tier.from_hours:
            continue
        upper = hours if tier.to_hours is None else min(tier.to_hours, hours)
        tier_hours = upper - tier.from_hours
        if tier_hours > 0:
            buckets.append(PaidBucket(hours=tier_hours, multiplier=tier.multiplier))
    return buckets


def compute_daily_overtime(
    worked_hours: Decimal, daily_threshold: Decimal, daily_tiers: list[TierSpec]
) -> tuple[Decimal, list[PaidBucket]]:
    """Split one day's worked hours into (regular_hours, overtime_buckets).

    ``regular_hours`` is capped at ``daily_threshold`` — hours above it
    are entirely accounted for by ``overtime_buckets`` instead, so the
    two never overlap.
    """
    if worked_hours <= daily_threshold:
        return worked_hours, []

    overtime_hours = worked_hours - daily_threshold
    return daily_threshold, apply_tiers(overtime_hours, daily_tiers)


def compute_weekly_overtime(
    daily_results: list[tuple[date, Decimal, Decimal]],
    weekly_threshold: Decimal,
    weekly_tiers: list[TierSpec],
) -> list[PaidBucket]:
    """Weekly OT on hours not already counted as daily OT.

    ``daily_results`` is each day's (date, regular_hours,
    daily_overtime_hours) for the week, as produced by
    ``compute_daily_overtime``. Weekly OT applies to
    ``max(0, total_regular_hours_across_week - weekly_threshold)`` — the
    daily-OT hours are already excluded from each day's "regular" hours,
    so summing regular hours alone (not total worked hours) is what
    prevents double-counting the same hour under both a daily and a
    weekly multiplier.
    """
    total_regular_hours = sum(
        (regular_hours for _, regular_hours, _ in daily_results), Decimal("0")
    )
    weekly_overtime_eligible = total_regular_hours - weekly_threshold
    if weekly_overtime_eligible <= 0:
        return []
    return apply_tiers(weekly_overtime_eligible, weekly_tiers)


def _to_tier_spec(tier: OvertimeTier) -> TierSpec:
    return TierSpec(
        from_hours=tier.from_hours, to_hours=tier.to_hours, multiplier=tier.multiplier
    )


def resolve_policy(organization_id: int, on_date: date) -> ResolvedPolicy | None:
    """Load the ``OvertimePolicy``/``OvertimeTier`` rows in force for
    ``organization_id`` on ``on_date`` and convert them into the plain
    dataclasses the pure functions above consume.

    This is the one place in this module that touches the database —
    kept as a thin wrapper, deliberately separate from the pure
    tiering logic. Returns ``None`` if no policy covers ``on_date`` (an
    organization with overtime tracking not yet configured).
    """
    policy = (
        db.session.query(OvertimePolicy)
        .filter(
            OvertimePolicy.organization_id == organization_id,
            OvertimePolicy.effective_from <= on_date,
            or_(
                OvertimePolicy.effective_to.is_(None),
                OvertimePolicy.effective_to >= on_date,
            ),
        )
        .one_or_none()
    )
    if policy is None:
        return None

    tiers = (
        db.session.query(OvertimeTier)
        .filter(OvertimeTier.policy_id == policy.id)
        .order_by(OvertimeTier.scope, OvertimeTier.tier_order)
        .all()
    )
    daily_tiers = [_to_tier_spec(tier) for tier in tiers if tier.scope == "daily"]
    weekly_tiers = [_to_tier_spec(tier) for tier in tiers if tier.scope == "weekly"]

    return ResolvedPolicy(
        policy_id=policy.id,
        daily_threshold_hours=policy.daily_threshold_hours,
        weekly_threshold_hours=policy.weekly_threshold_hours,
        week_start_day=policy.week_start_day,
        daily_tiers=daily_tiers,
        weekly_tiers=weekly_tiers,
    )
