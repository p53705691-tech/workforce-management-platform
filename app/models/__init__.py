"""Model import aggregator.

Import model modules here as they are added in later milestones so that
Alembic autogeneration and ``db.metadata`` can discover every table.
"""

from app.models.attendance_entry import AttendanceEntry
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.department_manager import DepartmentManager
from app.models.employee import Employee
from app.models.employee_pay_rate import EmployeePayRate
from app.models.job_location import JobLocation
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.organization import Organization
from app.models.overtime_policy import OvertimePolicy
from app.models.overtime_tier import OvertimeTier
from app.models.password_reset_token import PasswordResetToken
from app.models.shift import Shift
from app.models.user import User

__all__ = [
    "AttendanceEntry",
    "AuditLog",
    "Department",
    "DepartmentManager",
    "Employee",
    "EmployeePayRate",
    "JobLocation",
    "LeaveRequest",
    "LeaveType",
    "Organization",
    "OvertimePolicy",
    "OvertimeTier",
    "PasswordResetToken",
    "Shift",
    "User",
]
