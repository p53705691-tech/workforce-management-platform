"""Employee availability checks — read-only.

This module deliberately contains no writes and imports neither
``app.services.scheduling`` nor ``app.services.leave`` — only their
underlying models. Both of those *service* modules import this one, so
``scheduling``/``leave`` can each depend on a shared "is this employee
already busy?" query (shift overlap, and now approved-leave overlap)
without ever importing each other, avoiding a circular import between the
two domains.
"""

from datetime import datetime

from app.auth.scope import AccessScope
from app.extensions import db
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.shift import Shift


def shifts_overlapping(
    scope: AccessScope,
    employee_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_shift_id: int | None = None,
) -> list[Shift]:
    """Return the employee's active shifts overlapping [starts_at, ends_at).

    "Active" excludes cancelled shifts — a cancelled shift never blocks a
    new one, mirroring the database's exclusion constraint. This is a
    best-effort, read-only check for friendly pre-validation; it is not
    itself race-free (see ``app.services.scheduling`` for the actual
    authority, the database's EXCLUDE constraint).
    """
    query = db.session.query(Shift).filter(
        Shift.organization_id == scope.organization_id,
        Shift.employee_id == employee_id,
        Shift.status != "cancelled",
        Shift.starts_at < ends_at,
        Shift.ends_at > starts_at,
    )
    if exclude_shift_id is not None:
        query = query.filter(Shift.id != exclude_shift_id)
    return query.all()


def approved_leave_overlapping(
    scope: AccessScope,
    employee_id: int,
    starts_at: datetime,
    ends_at: datetime,
) -> list[LeaveRequest]:
    """Return the employee's approved leave overlapping [starts_at, ends_at).

    Only leave types with ``blocks_scheduling`` true count as a
    conflict — a leave type deliberately marked false (e.g. jury duty
    acknowledged but still on-call, see ``LeaveType.blocks_scheduling``'s
    own docstring) never blocks a shift. Same best-effort, read-only
    shape as ``shifts_overlapping``: race-free enforcement is not this
    function's job, it exists for friendly pre-validation before a write.
    """
    return (
        db.session.query(LeaveRequest)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .filter(
            LeaveRequest.organization_id == scope.organization_id,
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == "approved",
            LeaveType.blocks_scheduling.is_(True),
            LeaveRequest.starts_at < ends_at,
            LeaveRequest.ends_at > starts_at,
        )
        .all()
    )
