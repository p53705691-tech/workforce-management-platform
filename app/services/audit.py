"""Audit logging: a single, append-only entry point for privileged actions.

Every audit event goes through ``record`` — no route or service ever
constructs an ``AuditLog`` row directly, so every event is captured the
same way and no update/delete path for this table exists anywhere in the
codebase.

``changes`` must always stay a small, non-sensitive summary of what
happened, never a raw dump of a sensitive value. In particular, a
pay-rate change records that a rate was set (by whom, for whom,
effective when), never the rate value itself — audit logs may be read
more broadly within an organization than the pay-rate feature they
describe (see ``app.services.pay_rates.set_pay_rate``'s call site).

Round A fix — ``record`` stages the entry (``db.session.add``) but never
commits. Every call site must call ``record`` *before* the single commit
that already covers its own primary write, so the primary change and its
audit row land in one transaction: if the process crashes, or a later
step in the same call raises, between two separate commits, the primary
write could persist with no audit trail at all, silently. If a call
site's primary write must commit before its entity's id is known, use
``flush()`` (not ``commit()``) to obtain the id, stage the audit entry,
then commit once — never commit the primary write on its own first.

Round C fix — ``list_entries`` is the one read path this module exposes:
before this fix, ``app.routes.audit`` built and executed its own
``db.session.query(AuditLog)`` inline, the one route in this codebase
that queried the database directly instead of going through a service.
Reading the log is still admin-only (enforced here too, defensively,
independent of the route's own ``role_required("admin")`` — same
belt-and-suspenders pattern used throughout this codebase), org-scoped,
date-range-bounded, and paginated, exactly as it always was.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from flask import abort, has_request_context, request

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.audit_log import AuditLog

# Bounds how many rows a single request can pull back regardless of how
# wide a date range is requested, so a read can never load an unbounded
# table (per this milestone's explicit constraint).
DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class AuditLogPage:
    """One page of an organization's audit log, plus whether another
    page follows -- everything ``app.routes.audit`` needs to render the
    list view without ever touching ``AuditLog``/``db.session`` itself.
    """

    entries: list[AuditLog]
    has_next: bool


def record(
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    organization_id: int | None = None,
    actor_user_id: int | None = None,
    changes: dict | None = None,
) -> AuditLog:
    """Stage one audit event on the current session, without committing.

    ``ip_address`` is not a parameter: it is read from the current
    request automatically (when one is active) so every call site stays
    a plain, minimal one-liner rather than needing to thread the request
    through every service function that wants to log something.

    Deliberately does not call ``db.session.commit()`` — the caller's
    own commit for the primary write it describes must cover this entry
    too, so the two can never land as two separate transactions (see
    module docstring).
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        ip_address=request.remote_addr if has_request_context() else None,
    )
    db.session.add(entry)
    return entry


def list_entries(
    scope: AccessScope,
    start: date,
    end: date,
    page: int,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> AuditLogPage:
    """One page of ``scope``'s organization's audit log, most recent first.

    Admin only — this view can surface far more about an organization's
    day-to-day operations than any single domain view does (see
    ``app.routes.audit``'s module docstring), so it is never
    manager-reachable, enforced here independent of the route's own
    ``role_required("admin")``.

    ``start``/``end`` are calendar dates; ``created_at`` is a
    ``timestamptz``, so the comparison bounds are built explicitly in
    UTC rather than compared to a bare date (never rely on an ambient
    session timezone — see CLAUDE.md's time-and-money rule).
    """
    if scope.role != "admin":
        abort(403)

    range_start = datetime.combine(start, time.min, tzinfo=timezone.utc)
    range_end = datetime.combine(end, time.min, tzinfo=timezone.utc) + timedelta(days=1)

    query = (
        db.session.query(AuditLog)
        .filter(
            AuditLog.organization_id == scope.organization_id,
            AuditLog.created_at >= range_start,
            AuditLog.created_at < range_end,
        )
        .order_by(AuditLog.created_at.desc())
    )
    total = query.count()
    entries = query.offset((page - 1) * page_size).limit(page_size).all()
    has_next = page * page_size < total
    return AuditLogPage(entries=entries, has_next=has_next)
