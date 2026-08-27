"""Pay rate service: admin-only management of employee hourly rates.

Hourly rate only for MVP (confirmed rule): every employee has a Decimal
hourly rate. Pay rates are more sensitive than labor cost totals
(confirmed rule A4 for this milestone) — every function that exposes a
rate value here is admin-only, never manager, even though a manager may
view labor cost *totals* via ``app.services.labor_cost``.

Rate changes never overwrite history: a new rate is always a new row
with its own effective date range (see ``app.models.employee_pay_rate``),
so the cost of an already-worked historical period is never silently
recomputed just because the current rate changed.
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import abort
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.employee import Employee
from app.models.employee_pay_rate import EmployeePayRate
from app.services import audit as audit_service
from app.services.errors import ValidationError

# Name of the DB's overlap-prevention exclusion constraint (see migration
# 0012_create_employee_pay_rates). Matched against IntegrityError.orig.diag
# so a race that slips past this module's best-effort ordering still
# surfaces as a clean ValidationError instead of a raw 500 — same pattern
# as app.services.leave's overlap handling.
_OVERLAP_EXCLUSION_CONSTRAINT = "ex_employee_pay_rates_employee_no_overlap"


def _validate_employee_for_scope(scope: AccessScope, employee_id: int) -> Employee:
    """Confirm ``employee_id`` exists in the caller's organization.

    Every caller of this module is already required to be an admin (org-
    wide access), so no department restriction applies here — this only
    turns a cross-tenant or nonexistent id into a clean ``ValidationError``
    instead of a raw ``IntegrityError``/``None`` surprise, same pattern as
    ``app.services.leave._validate_employee_for_scope``.
    """
    employee = (
        db.session.query(Employee)
        .filter(
            Employee.id == employee_id,
            Employee.organization_id == scope.organization_id,
        )
        .first()
    )
    if employee is None:
        raise ValidationError(
            "Selected employee does not exist in this organization.",
            field="employee_id",
        )
    return employee


def _flush_or_raise_overlap() -> None:
    """Flush the pending pay-rate insert to detect an overlap conflict
    early, without committing — the exclusion constraint (not
    deferrable) is checked at statement execution time, so a flush is
    enough. The actual commit happens once, later, alongside the audit
    entry (see app.services.audit's module docstring for why the two
    must land in one transaction).
    """
    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        constraint_name = getattr(
            getattr(error.orig, "diag", None), "constraint_name", None
        )
        if constraint_name == _OVERLAP_EXCLUSION_CONSTRAINT:
            raise ValidationError(
                "This employee already has a pay rate covering part of "
                "that date range."
            ) from error
        raise


def set_pay_rate(
    scope: AccessScope,
    employee_id: int,
    hourly_rate: Decimal,
    effective_from: date,
    effective_to: date | None = None,
) -> EmployeePayRate:
    """Record a new hourly rate period for an employee. Admin only.

    Never a manager: pay rates are strictly more sensitive than the
    labor-cost totals a manager may already see (confirmed rule A4).
    """
    if scope.role != "admin":
        abort(403)

    _validate_employee_for_scope(scope, employee_id)

    if hourly_rate <= 0:
        raise ValidationError(
            "Hourly rate must be greater than zero.", field="hourly_rate"
        )
    if effective_to is not None and effective_to < effective_from:
        raise ValidationError(
            "Effective-to date must be on or after the effective-from date.",
            field="effective_to",
        )

    pay_rate = EmployeePayRate(
        employee_id=employee_id,
        organization_id=scope.organization_id,
        hourly_rate=hourly_rate,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.session.add(pay_rate)
    _flush_or_raise_overlap()
    # changes deliberately excludes hourly_rate itself (see
    # app.services.audit's module docstring and this module's own): only
    # who/for whom/when a rate was set is recorded, never the number.
    audit_service.record(
        "pay_rate_set",
        "employee",
        entity_id=employee_id,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        changes={
            "effective_from": effective_from.isoformat(),
            "effective_to": effective_to.isoformat() if effective_to else None,
        },
    )
    # One commit covers both the pay-rate insert and the audit entry
    # above — see app.services.audit's module docstring.
    db.session.commit()
    return pay_rate


def resolve_pay_rate(
    employee_id: int, organization_id: int, on_date: date
) -> Decimal | None:
    """The hourly rate in force for ``employee_id`` on ``on_date``, or
    ``None`` if unconfigured.

    Thin DB wrapper, mirrors the shape of
    ``app.services.overtime.resolve_policy``. Deliberately takes no
    ``AccessScope`` and does no authorization of its own: this is a
    low-level lookup consumed internally by
    ``app.services.labor_cost`` (which already validated the caller may
    see this employee's hours before ever reaching here), not a route-
    reachable operation in its own right. It must never be exposed
    directly to a manager — that boundary is enforced by
    ``app.services.labor_cost`` never handing a raw rate back to a
    manager-reachable code path.
    """
    pay_rate = (
        db.session.query(EmployeePayRate)
        .filter(
            EmployeePayRate.employee_id == employee_id,
            EmployeePayRate.organization_id == organization_id,
            EmployeePayRate.effective_from <= on_date,
            or_(
                EmployeePayRate.effective_to.is_(None),
                EmployeePayRate.effective_to >= on_date,
            ),
        )
        .one_or_none()
    )
    return pay_rate.hourly_rate if pay_rate is not None else None


def resolve_pay_rates_by_range(
    employee_id: int, organization_id: int, start_date: date, end_date: date
) -> dict[date, Decimal]:
    """The hourly rate in force on each date in ``[start_date, end_date]``
    that has one configured — a missing key means "unconfigured", same as
    ``resolve_pay_rate`` returning ``None`` for that date.

    One query for the whole range instead of ``resolve_pay_rate`` called
    once per day — see ``working_hours.worked_seconds_by_range``'s
    docstring for the N+1 problem this (and its two siblings) fixes.
    Rate periods never overlap (the DB's own exclusion constraint), so at
    most one fetched row can match any given date; the per-date match is
    a cheap in-memory scan over what is typically a handful of rows, not
    a second query.
    """
    rows = (
        db.session.query(EmployeePayRate)
        .filter(
            EmployeePayRate.employee_id == employee_id,
            EmployeePayRate.organization_id == organization_id,
            EmployeePayRate.effective_from <= end_date,
            or_(
                EmployeePayRate.effective_to.is_(None),
                EmployeePayRate.effective_to >= start_date,
            ),
        )
        .all()
    )
    if not rows:
        return {}

    rate_by_date: dict[date, Decimal] = {}
    business_date = start_date
    one_day = timedelta(days=1)
    while business_date <= end_date:
        for row in rows:
            if row.effective_from <= business_date and (
                row.effective_to is None or row.effective_to >= business_date
            ):
                rate_by_date[business_date] = row.hourly_rate
                break
        business_date += one_day
    return rate_by_date


def list_pay_rate_history(scope: AccessScope, employee_id: int) -> list[EmployeePayRate]:
    """Full rate history for an employee, most recent first. Admin only —
    managers never see this, per confirmed rule A4.
    """
    if scope.role != "admin":
        abort(403)

    _validate_employee_for_scope(scope, employee_id)

    return (
        db.session.query(EmployeePayRate)
        .filter(
            EmployeePayRate.employee_id == employee_id,
            EmployeePayRate.organization_id == scope.organization_id,
        )
        .order_by(EmployeePayRate.effective_from.desc())
        .all()
    )
