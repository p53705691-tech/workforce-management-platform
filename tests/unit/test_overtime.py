"""Unit tests for app.services.overtime — pure functions, no DB, no I/O.

Uses the confirmed default policy shape throughout: daily threshold 8h
(tiers: 0-2h beyond threshold @1.5x, 2h+ @2.0x) and weekly threshold 40h
(tier: beyond threshold @1.5x).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.overtime import (
    PaidBucket,
    TierSpec,
    apply_tiers,
    compute_daily_overtime,
    compute_weekly_overtime,
)

pytestmark = pytest.mark.unit

DAILY_THRESHOLD = Decimal("8")
WEEKLY_THRESHOLD = Decimal("40")
DAILY_TIERS = [
    TierSpec(from_hours=Decimal("0"), to_hours=Decimal("2"), multiplier=Decimal("1.5")),
    TierSpec(from_hours=Decimal("2"), to_hours=None, multiplier=Decimal("2.0")),
]
WEEKLY_TIERS = [
    TierSpec(from_hours=Decimal("0"), to_hours=None, multiplier=Decimal("1.5")),
]


class TestApplyTiers:
    def test_zero_hours_returns_no_buckets(self):
        assert apply_tiers(Decimal("0"), DAILY_TIERS) == []

    def test_negative_hours_returns_no_buckets(self):
        assert apply_tiers(Decimal("-1"), DAILY_TIERS) == []

    def test_hours_within_first_tier_only(self):
        assert apply_tiers(Decimal("1"), DAILY_TIERS) == [
            PaidBucket(hours=Decimal("1"), multiplier=Decimal("1.5"))
        ]

    def test_hours_exactly_filling_first_tier(self):
        assert apply_tiers(Decimal("2"), DAILY_TIERS) == [
            PaidBucket(hours=Decimal("2"), multiplier=Decimal("1.5"))
        ]

    def test_hours_spilling_into_second_tier(self):
        assert apply_tiers(Decimal("3"), DAILY_TIERS) == [
            PaidBucket(hours=Decimal("2"), multiplier=Decimal("1.5")),
            PaidBucket(hours=Decimal("1"), multiplier=Decimal("2.0")),
        ]

    def test_tiers_out_of_order_are_still_applied_correctly(self):
        reversed_tiers = list(reversed(DAILY_TIERS))
        assert apply_tiers(Decimal("3"), reversed_tiers) == [
            PaidBucket(hours=Decimal("2"), multiplier=Decimal("1.5")),
            PaidBucket(hours=Decimal("1"), multiplier=Decimal("2.0")),
        ]

    def test_single_unbounded_tier_absorbs_everything(self):
        assert apply_tiers(Decimal("8"), WEEKLY_TIERS) == [
            PaidBucket(hours=Decimal("8"), multiplier=Decimal("1.5"))
        ]


class TestComputeDailyOvertime:
    @pytest.mark.parametrize(
        "worked_hours, expected_regular, expected_buckets",
        [
            (Decimal("0"), Decimal("0"), []),
            (Decimal("8"), Decimal("8"), []),
            (
                Decimal("9"),
                Decimal("8"),
                [PaidBucket(hours=Decimal("1"), multiplier=Decimal("1.5"))],
            ),
            (
                Decimal("10"),
                Decimal("8"),
                [PaidBucket(hours=Decimal("2"), multiplier=Decimal("1.5"))],
            ),
            (
                Decimal("11"),
                Decimal("8"),
                [
                    PaidBucket(hours=Decimal("2"), multiplier=Decimal("1.5")),
                    PaidBucket(hours=Decimal("1"), multiplier=Decimal("2.0")),
                ],
            ),
        ],
    )
    def test_daily_overtime_tiers(
        self, worked_hours, expected_regular, expected_buckets
    ):
        regular_hours, buckets = compute_daily_overtime(
            worked_hours, DAILY_THRESHOLD, DAILY_TIERS
        )
        assert regular_hours == expected_regular
        assert buckets == expected_buckets

    def test_worked_hours_below_threshold_are_all_regular(self):
        regular_hours, buckets = compute_daily_overtime(
            Decimal("6"), DAILY_THRESHOLD, DAILY_TIERS
        )
        assert regular_hours == Decimal("6")
        assert buckets == []


class TestComputeWeeklyOvertime:
    def test_zero_hours_worked_all_week_has_no_overtime(self):
        daily_results = [
            (date(2026, 1, 5 + i), Decimal("0"), Decimal("0")) for i in range(7)
        ]
        assert compute_weekly_overtime(daily_results, WEEKLY_THRESHOLD, WEEKLY_TIERS) == []

    def test_exactly_at_weekly_threshold_with_no_daily_overtime(self):
        # 8h x 5 days = 40h total, exactly at the weekly threshold.
        daily_results = [
            (date(2026, 1, 5 + i), Decimal("8"), Decimal("0")) for i in range(5)
        ]
        assert compute_weekly_overtime(daily_results, WEEKLY_THRESHOLD, WEEKLY_TIERS) == []

    def test_daily_overtime_hours_are_excluded_from_the_weekly_regular_sum(self):
        # One 10h day (8h regular + 2h daily OT) plus four 8h days: regular
        # hours across the week are 8*4 + 8 = 40, exactly at the weekly
        # threshold, even though total worked hours (42) exceed it. The
        # 2h of daily OT must not also count toward weekly OT.
        daily_results = [
            (date(2026, 1, 5), Decimal("8"), Decimal("2")),
        ] + [(date(2026, 1, 6 + i), Decimal("8"), Decimal("0")) for i in range(4)]
        assert compute_weekly_overtime(daily_results, WEEKLY_THRESHOLD, WEEKLY_TIERS) == []

    def test_regular_hours_alone_exceeding_weekly_threshold_trigger_weekly_overtime(
        self,
    ):
        # Six 9h days: each day's regular hours are capped at 8 (1h daily
        # OT per day, not relevant here), so regular hours across the
        # week total 48 -- 8h beyond the 40h weekly threshold.
        daily_results = [
            (date(2026, 1, 5 + i), Decimal("8"), Decimal("1")) for i in range(6)
        ]
        buckets = compute_weekly_overtime(daily_results, WEEKLY_THRESHOLD, WEEKLY_TIERS)
        assert buckets == [PaidBucket(hours=Decimal("8"), multiplier=Decimal("1.5"))]

    def test_regular_hours_below_weekly_threshold_have_no_weekly_overtime(self):
        daily_results = [
            (date(2026, 1, 5 + i), Decimal("6"), Decimal("0")) for i in range(5)
        ]
        assert compute_weekly_overtime(daily_results, WEEKLY_THRESHOLD, WEEKLY_TIERS) == []
