"""Flask CLI commands for maintenance operations.

Registered on the app in ``create_app`` (see ``app/__init__.py``), same
place every blueprint gets registered. These are operator-invoked
maintenance tasks, not user-facing routes, so they live outside
``app/routes``.
"""

from datetime import date
from decimal import Decimal

import click
from flask import Flask

from app.extensions import db
from app.models.organization import Organization
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from app.services import attendance as attendance_service

# Seed data is environment data, not schema (per CLAUDE.md's architecture
# plan), so the confirmed default policy is created here via a CLI
# command rather than baked into a migration. Fixed epoch, well before
# any real organization's data, so a newly seeded policy covers every
# historical attendance record without needing a per-organization
# "creation date" lookup.
_SEED_POLICY_EFFECTIVE_FROM = date(2020, 1, 1)


def register_cli(app: Flask) -> None:
    @app.cli.group("attendance")
    def attendance_group():
        """Attendance maintenance commands."""

    @attendance_group.command("flag-stale")
    @click.option(
        "--cutoff-hours",
        default=16,
        show_default=True,
        type=int,
        help="Hours since clock-in after which an open entry with no "
        "clock-out is flagged for review (confirmed rule A11).",
    )
    def flag_stale(cutoff_hours: int) -> None:
        """Mark stale open attendance entries as needs_review.

        Intended to run periodically (e.g. via cron) rather than needing
        a background scheduler in the MVP.
        """
        count = attendance_service.flag_stale_open_entries(cutoff_hours=cutoff_hours)
        entry_word = "entry" if count == 1 else "entries"
        click.echo(f"Flagged {count} stale open attendance {entry_word} for review.")

    @app.cli.group("seed")
    def seed_group():
        """One-off environment data seeding commands."""

    @seed_group.command("overtime-policy")
    @click.option(
        "--organization",
        "organization_slug",
        required=True,
        help="Slug of the organization to seed a default overtime policy for.",
    )
    def seed_overtime_policy(organization_slug: str) -> None:
        """Seed the confirmed default overtime policy for one organization.

        8h daily / 40h weekly thresholds; daily tiers 0-2h beyond
        threshold at 1.5x and 2h+ at 2.0x; weekly tier beyond threshold
        at 1.5x. Refuses to run if the organization already has any
        overtime policy — reconfiguring an existing policy is a real
        effective-dated business change, not something this one-shot
        seed command should guess at.
        """
        organization = (
            db.session.query(Organization)
            .filter(Organization.slug == organization_slug)
            .first()
        )
        if organization is None:
            raise click.ClickException(
                f"No organization found with slug {organization_slug!r}."
            )

        existing_policy = (
            db.session.query(OvertimePolicy)
            .filter(OvertimePolicy.organization_id == organization.id)
            .first()
        )
        if existing_policy is not None:
            raise click.ClickException(
                f"Organization {organization_slug!r} already has an "
                "overtime policy; this seed command only applies to "
                "unconfigured organizations."
            )

        policy = OvertimePolicy(
            organization_id=organization.id,
            name="Default Overtime Policy",
            daily_threshold_hours=Decimal("8.00"),
            weekly_threshold_hours=Decimal("40.00"),
            week_start_day=0,
            effective_from=_SEED_POLICY_EFFECTIVE_FROM,
            effective_to=None,
        )
        db.session.add(policy)
        db.session.flush()

        db.session.add_all(
            [
                OvertimeTier(
                    policy_id=policy.id,
                    scope="daily",
                    tier_order=0,
                    from_hours=Decimal("0.00"),
                    to_hours=Decimal("2.00"),
                    multiplier=Decimal("1.50"),
                ),
                OvertimeTier(
                    policy_id=policy.id,
                    scope="daily",
                    tier_order=1,
                    from_hours=Decimal("2.00"),
                    to_hours=None,
                    multiplier=Decimal("2.00"),
                ),
                OvertimeTier(
                    policy_id=policy.id,
                    scope="weekly",
                    tier_order=0,
                    from_hours=Decimal("0.00"),
                    to_hours=None,
                    multiplier=Decimal("1.50"),
                ),
            ]
        )
        db.session.commit()
        click.echo(
            f"Seeded default overtime policy for organization {organization_slug!r}."
        )
