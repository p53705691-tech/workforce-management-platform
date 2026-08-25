"""Audit log route: a read-only, admin-only view of ``app.services.audit``'s
append-only event log.

Never manager-reachable, no exceptions: this view can surface far more
about an organization's day-to-day operations across every domain (who
signed in when, whose pay rate changed and for whom, which leave request
was approved) than any single domain view does, so it stays strictly
admin-only rather than following the "manager sees totals, admin sees
detail" split used elsewhere (e.g. ``app.routes.labor_cost``).

Every view builds an ``AccessScope`` from the signed-in user and delegates
all authorization and data access to ``app.services.audit`` — no route
here queries the database directly.
"""

from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.auth.decorators import role_required
from app.auth.scope import build_scope_for_user
from app.services import audit as audit_service
from app.services import reports as report_service
from app.services import scheduling as scheduling_service

audit_bp = Blueprint("audit", __name__)

# Default visible window when no ?start=/&end= query params are given,
# same "trailing week" default used by app.routes.labor_cost.
_DEFAULT_WINDOW_DAYS = 6


def _default_date_range(scope) -> tuple[date, date]:
    # Round B fix: org-local "today" (rule A1), not the server's — see
    # app.routes.schedule's identical fix for the full rationale.
    today = report_service.today_business_date(scope)
    return today - timedelta(days=_DEFAULT_WINDOW_DAYS), today


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


@audit_bp.route("/audit-log", methods=["GET"])
@role_required("admin")
def list_entries():
    scope = build_scope_for_user(current_user)
    default_start, default_end = _default_date_range(scope)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    page = max(request.args.get("page", default=1, type=int), 1)

    result = audit_service.list_entries(scope, start, end, page)

    return render_template(
        "audit/list.html",
        entries=result.entries,
        start=start,
        end=end,
        page=page,
        has_next=result.has_next,
        tz=scheduling_service.organization_timezone(scope),
    )
