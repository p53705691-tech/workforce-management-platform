"""Integration tests for app.services.overtime.resolve_policy.

The pure tiering functions are unit-tested (no DB) in
tests/unit/test_overtime.py; this file only covers the thin,
DB-touching wrapper that loads the effective policy/tiers for an
organization on a given date.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.errors import ValidationError
from app.services.overtime import TierSpec, resolve_policy
from tests.factories import make_organization, make_overtime_policy, make_overtime_tier

pytestmark = pytest.mark.integration


def test_resolve_policy_returns_none_when_no_policy_covers_the_date(db_session):
    org = make_organization(db_session)
    assert resolve_policy(org.id, date(2026, 1, 1)) is None


def test_resolve_policy_picks_the_policy_in_force_among_several_historical_ones(
    db_session,
):
    org = make_organization(db_session)
    old_policy = make_overtime_policy(
        db_session,
        organization=org,
        daily_threshold_hours=Decimal("7.50"),
        effective_from=date(2020, 1, 1),
        effective_to=date(2021, 12, 31),
    )
    current_policy = make_overtime_policy(
        db_session,
        organization=org,
        daily_threshold_hours=Decimal("8.00"),
        effective_from=date(2022, 1, 1),
        effective_to=None,
    )
    make_overtime_tier(db_session, policy=old_policy, scope="daily", tier_order=0)
    make_overtime_tier(db_session, policy=current_policy, scope="daily", tier_order=0)

    resolved_during_old_policy = resolve_policy(org.id, date(2021, 6, 1))
    resolved_during_current_policy = resolve_policy(org.id, date(2026, 1, 1))

    assert resolved_during_old_policy.policy_id == old_policy.id
    assert resolved_during_old_policy.daily_threshold_hours == Decimal("7.50")
    assert resolved_during_current_policy.policy_id == current_policy.id
    assert resolved_during_current_policy.daily_threshold_hours == Decimal("8.00")


def test_resolve_policy_converts_tiers_into_tier_specs_split_by_scope(db_session):
    org = make_organization(db_session)
    policy = make_overtime_policy(db_session, organization=org)
    make_overtime_tier(
        db_session,
        policy=policy,
        scope="daily",
        tier_order=0,
        from_hours=Decimal("0.00"),
        to_hours=Decimal("2.00"),
        multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        db_session,
        policy=policy,
        scope="daily",
        tier_order=1,
        from_hours=Decimal("2.00"),
        to_hours=None,
        multiplier=Decimal("2.00"),
    )
    make_overtime_tier(
        db_session,
        policy=policy,
        scope="weekly",
        tier_order=0,
        from_hours=Decimal("0.00"),
        to_hours=None,
        multiplier=Decimal("1.50"),
    )

    resolved = resolve_policy(org.id, date(2026, 1, 1))

    assert resolved.daily_tiers == [
        TierSpec(from_hours=Decimal("0.00"), to_hours=Decimal("2.00"), multiplier=Decimal("1.50")),
        TierSpec(from_hours=Decimal("2.00"), to_hours=None, multiplier=Decimal("2.00")),
    ]
    assert resolved.weekly_tiers == [
        TierSpec(from_hours=Decimal("0.00"), to_hours=None, multiplier=Decimal("1.50")),
    ]


def test_resolve_policy_rejects_a_gap_between_tiers(db_session):
    """Data/business-logic finding: nothing in the DB stops a gap between
    tiers (uniqueness is only on (policy_id, scope, from_hours)), which
    would otherwise silently pay genuinely-overtime hours at 1x.
    """
    org = make_organization(db_session)
    policy = make_overtime_policy(db_session, organization=org)
    make_overtime_tier(
        db_session, policy=policy, scope="daily", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=Decimal("2.00"), multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        db_session, policy=policy, scope="daily", tier_order=1,
        from_hours=Decimal("4.00"), to_hours=None, multiplier=Decimal("2.00"),
    )

    with pytest.raises(ValidationError, match="gap or overlap"):
        resolve_policy(org.id, date(2026, 1, 1))


def test_resolve_policy_rejects_overlapping_tiers(db_session):
    """Same finding, the other direction: an overlap would silently pay
    some hours at two multipliers combined.
    """
    org = make_organization(db_session)
    policy = make_overtime_policy(db_session, organization=org)
    make_overtime_tier(
        db_session, policy=policy, scope="weekly", tier_order=0,
        from_hours=Decimal("0.00"), to_hours=Decimal("5.00"), multiplier=Decimal("1.50"),
    )
    make_overtime_tier(
        db_session, policy=policy, scope="weekly", tier_order=1,
        from_hours=Decimal("2.00"), to_hours=None, multiplier=Decimal("2.00"),
    )

    with pytest.raises(ValidationError, match="gap or overlap"):
        resolve_policy(org.id, date(2026, 1, 1))


def test_resolve_policy_allows_a_scope_with_no_tiers_at_all(db_session):
    """A policy that only tracks weekly OT (daily_threshold_hours set
    high enough that daily OT never triggers) has zero daily tiers by
    design — this must not be treated as a configuration error.
    """
    org = make_organization(db_session)
    policy = make_overtime_policy(
        db_session, organization=org, daily_threshold_hours=Decimal("24.00")
    )
    make_overtime_tier(db_session, policy=policy, scope="weekly", tier_order=0)

    resolved = resolve_policy(org.id, date(2026, 1, 1))

    assert resolved.daily_tiers == []
    assert len(resolved.weekly_tiers) == 1


def test_resolve_policy_is_scoped_to_the_given_organization(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    make_overtime_policy(db_session, organization=org_a)

    assert resolve_policy(org_b.id, date(2026, 1, 1)) is None
