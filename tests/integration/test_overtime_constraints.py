"""DB-level constraint coverage for overtime_policies / overtime_tiers.

Mirrors tests/integration/test_shift_constraints.py's approach: exercise
constraints directly against the model (bypassing the service layer) to
confirm the database itself protects these invariants. The exclusion
constraint on overtime_policies is the single most important test here —
it is the actual "exactly one policy in force per org per day" guarantee.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from tests.factories import make_organization, make_overtime_policy, make_overtime_tier

pytestmark = pytest.mark.integration


def _policy_kwargs(org, **overrides):
    defaults = {
        "organization_id": org.id,
        "name": "Policy",
        "daily_threshold_hours": Decimal("8.00"),
        "weekly_threshold_hours": Decimal("40.00"),
        "week_start_day": 0,
        "effective_from": date(2020, 1, 1),
        "effective_to": None,
    }
    defaults.update(overrides)
    return defaults


def test_exclusion_constraint_rejects_an_overlapping_policy_for_the_same_org(
    db_session,
):
    org = make_organization(db_session)
    make_overtime_policy(
        db_session,
        organization=org,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )

    overlapping = OvertimePolicy(
        **_policy_kwargs(
            org, effective_from=date(2021, 1, 1), effective_to=date(2021, 12, 31)
        )
    )
    db_session.add(overlapping)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_non_overlapping_policies_for_the_same_org_are_allowed(db_session):
    org = make_organization(db_session)
    make_overtime_policy(
        db_session,
        organization=org,
        effective_from=date(2020, 1, 1),
        effective_to=date(2020, 12, 31),
    )

    later = OvertimePolicy(
        **_policy_kwargs(org, effective_from=date(2021, 1, 1), effective_to=None)
    )
    db_session.add(later)

    db_session.flush()  # must not raise


def test_overlapping_policies_in_different_orgs_are_allowed(db_session):
    org_a = make_organization(db_session)
    org_b = make_organization(db_session)
    make_overtime_policy(
        db_session, organization=org_a, effective_from=date(2020, 1, 1), effective_to=None
    )

    same_range_other_org = OvertimePolicy(
        **_policy_kwargs(org_b, effective_from=date(2020, 1, 1), effective_to=None)
    )
    db_session.add(same_range_other_org)

    db_session.flush()  # must not raise: different organizations don't compete


def test_effective_to_before_effective_from_is_rejected(db_session):
    org = make_organization(db_session)

    policy = OvertimePolicy(
        **_policy_kwargs(
            org, effective_from=date(2021, 1, 1), effective_to=date(2020, 1, 1)
        )
    )
    db_session.add(policy)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_daily_threshold_hours_out_of_range_is_rejected(db_session):
    org = make_organization(db_session)

    policy = OvertimePolicy(
        **_policy_kwargs(org, daily_threshold_hours=Decimal("25.00"))
    )
    db_session.add(policy)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_week_start_day_out_of_range_is_rejected(db_session):
    org = make_organization(db_session)

    policy = OvertimePolicy(**_policy_kwargs(org, week_start_day=7))
    db_session.add(policy)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def _tier_kwargs(policy, **overrides):
    defaults = {
        "policy_id": policy.id,
        "scope": "daily",
        "tier_order": 0,
        "from_hours": Decimal("0.00"),
        "to_hours": Decimal("2.00"),
        "multiplier": Decimal("1.50"),
    }
    defaults.update(overrides)
    return defaults


def test_duplicate_tier_order_within_same_policy_and_scope_is_rejected(db_session):
    policy = make_overtime_policy(db_session)
    make_overtime_tier(db_session, policy=policy, scope="daily", tier_order=0, from_hours=Decimal("0.00"))

    duplicate = OvertimeTier(
        **_tier_kwargs(policy, tier_order=0, from_hours=Decimal("5.00"))
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_duplicate_from_hours_within_same_policy_and_scope_is_rejected(db_session):
    policy = make_overtime_policy(db_session)
    make_overtime_tier(db_session, policy=policy, scope="daily", tier_order=0, from_hours=Decimal("0.00"))

    duplicate = OvertimeTier(
        **_tier_kwargs(policy, tier_order=1, from_hours=Decimal("0.00"))
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_same_tier_order_is_allowed_across_different_scopes(db_session):
    policy = make_overtime_policy(db_session)
    make_overtime_tier(
        db_session, policy=policy, scope="daily", tier_order=0, from_hours=Decimal("0.00")
    )

    weekly_tier = OvertimeTier(
        **_tier_kwargs(policy, scope="weekly", tier_order=0, from_hours=Decimal("0.00"))
    )
    db_session.add(weekly_tier)

    db_session.flush()  # must not raise: uniqueness is scoped per (policy, scope)


def test_to_hours_not_greater_than_from_hours_is_rejected(db_session):
    policy = make_overtime_policy(db_session)

    tier = OvertimeTier(
        **_tier_kwargs(policy, from_hours=Decimal("2.00"), to_hours=Decimal("2.00"))
    )
    db_session.add(tier)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_tier_cascade_deletes_when_policy_is_deleted(db_session):
    policy = make_overtime_policy(db_session)
    tier = make_overtime_tier(db_session, policy=policy)
    tier_id = tier.id

    db_session.delete(policy)
    db_session.flush()
    # Session.get() would return the stale, already-loaded object straight
    # from the identity map without re-checking the database; a fresh
    # query is needed to actually observe the DB-level ON DELETE CASCADE.
    db_session.expire_all()

    remaining = (
        db_session.query(OvertimeTier).filter(OvertimeTier.id == tier_id).first()
    )
    assert remaining is None
