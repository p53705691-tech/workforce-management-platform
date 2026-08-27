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
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_

from app.extensions import db
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from app.services.errors import ValidationError


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


def _validate_tier_coverage(tiers: list[TierSpec], scope: str, policy_id: int) -> None:
    """Assert ``tiers`` (already sorted by ``from_hours``) form one
    contiguous, non-overlapping range starting at 0 with exactly one
    unbounded top tier (data/business-logic audit finding).

    ``apply_tiers`` has no way to detect a gap or an overlap on its own —
    it just walks whatever tiers it's given — so a gap silently pays
    genuine overtime at 1x, and an overlap silently pays some hours at
    two multipliers' worth combined. Neither is a user input mistake to
    show a form error for; it's a data-integrity problem with whatever
    created these rows (only ``flask seed`` today), caught here before
    it can reach a real payroll number.
    """
    if not tiers:
        # A scope with zero tiers is a legitimate, already-supported
        # configuration (e.g. a policy that only tracks weekly OT, with
        # daily_threshold_hours set high enough that daily OT never
        # triggers) — apply_tiers correctly returns no buckets for it.
        # Only a *non-empty* set of tiers with a gap or overlap is the
        # actual bug this guards against.
        return

    # Sorted by from_hours, not trusted from the caller's order: apply_tiers
    # itself re-sorts by from_hours before use (its own docstring notes a
    # tier row's DB order — here, tier_order — isn't a safe assumption),
    # so validation must check the same order pricing actually applies.
    tiers = sorted(tiers, key=lambda t: t.from_hours)
    expected_from = Decimal("0")
    for index, tier in enumerate(tiers):
        if tier.from_hours != expected_from:
            raise ValidationError(
                f"Overtime policy {policy_id}'s {scope} tiers have a gap or "
                f"overlap at {tier.from_hours} hours (expected {expected_from})."
            )
        is_last = index == len(tiers) - 1
        if is_last:
            if tier.to_hours is not None:
                raise ValidationError(
                    f"Overtime policy {policy_id}'s {scope} tiers have no "
                    "unbounded top tier."
                )
        else:
            if tier.to_hours is None:
                raise ValidationError(
                    f"Overtime policy {policy_id}'s {scope} tiers have an "
                    "unbounded tier before the last one."
                )
            expected_from = tier.to_hours


def _to_tier_spec(tier: OvertimeTier) -> TierSpec:
    return TierSpec(
        from_hours=tier.from_hours, to_hours=tier.to_hours, multiplier=tier.multiplier
    )


def _resolve_from_rows(policy: OvertimePolicy, tiers: list[OvertimeTier]) -> ResolvedPolicy:
    daily_tiers = [_to_tier_spec(tier) for tier in tiers if tier.scope == "daily"]
    weekly_tiers = [_to_tier_spec(tier) for tier in tiers if tier.scope == "weekly"]
    _validate_tier_coverage(daily_tiers, "daily", policy.id)
    _validate_tier_coverage(weekly_tiers, "weekly", policy.id)

    return ResolvedPolicy(
        policy_id=policy.id,
        daily_threshold_hours=policy.daily_threshold_hours,
        weekly_threshold_hours=policy.weekly_threshold_hours,
        week_start_day=policy.week_start_day,
        daily_tiers=daily_tiers,
        weekly_tiers=weekly_tiers,
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
    return _resolve_from_rows(policy, tiers)


def resolve_policies_by_range(
    organization_id: int, start_date: date, end_date: date
) -> dict[date, ResolvedPolicy | None]:
    """``resolve_policy`` for every date in ``[start_date, end_date]``, in
    two queries total (every policy overlapping the range, then every
    tier for those policies in one shot) instead of one call — and two
    queries — per date.

    A policy rarely changes, so this is normally one policy's worth of
    rows resolved once and reused for every date; it's still correct if
    the organization's policy actually changed mid-range, since the
    per-date match below re-checks each policy's own effective window.
    See ``working_hours.worked_seconds_by_range``'s docstring for the
    wider N+1 problem this (and its two siblings) fixes.
    """
    policies = (
        db.session.query(OvertimePolicy)
        .filter(
            OvertimePolicy.organization_id == organization_id,
            OvertimePolicy.effective_from <= end_date,
            or_(
                OvertimePolicy.effective_to.is_(None),
                OvertimePolicy.effective_to >= start_date,
            ),
        )
        .all()
    )
    if not policies:
        return {}

    tiers = (
        db.session.query(OvertimeTier)
        .filter(OvertimeTier.policy_id.in_([policy.id for policy in policies]))
        .order_by(OvertimeTier.policy_id, OvertimeTier.scope, OvertimeTier.tier_order)
        .all()
    )
    tiers_by_policy_id: dict[int, list[OvertimeTier]] = {}
    for tier in tiers:
        tiers_by_policy_id.setdefault(tier.policy_id, []).append(tier)

    resolved_by_policy_id = {
        policy.id: _resolve_from_rows(policy, tiers_by_policy_id.get(policy.id, []))
        for policy in policies
    }

    policy_by_date: dict[date, ResolvedPolicy | None] = {}
    business_date = start_date
    one_day = timedelta(days=1)
    while business_date <= end_date:
        match = next(
            (
                policy
                for policy in policies
                if policy.effective_from <= business_date
                and (policy.effective_to is None or policy.effective_to >= business_date)
            ),
            None,
        )
        policy_by_date[business_date] = (
            resolved_by_policy_id[match.id] if match is not None else None
        )
        business_date += one_day
    return policy_by_date
