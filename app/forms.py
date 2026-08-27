"""WTForms forms.

Kept as a single flat module for now: split into a package if/when later
milestones add enough forms to justify it.
"""

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DateTimeLocalField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
)
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange, Optional


class LoginForm(FlaskForm):
    # No format validator (e.g. WTForms' Email()) here: it depends on the
    # optional `email_validator` package, which isn't a project dependency.
    # Format doesn't matter for login anyway — an invalid-format value
    # simply won't match any account and falls into the same generic error.
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=255)])


class OptionalDecimalField(DecimalField):
    """A ``DecimalField`` that treats a blank submission as absent.

    WTForms' stock ``DecimalField`` raises a "Not a valid decimal value"
    process error for an empty string even when paired with an
    ``Optional()`` validator, because the Decimal conversion happens
    before validators ever run (``Field.validate`` seeds ``self.errors``
    from ``process_errors`` regardless of what validators decide
    afterwards). Treating blank input as ``None`` up front avoids that.
    """

    def process_formdata(self, valuelist):
        if valuelist and valuelist[0].strip() == "":
            self.data = None
            return
        super().process_formdata(valuelist)


class DepartmentForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    code = StringField("Code", validators=[DataRequired(), Length(max=50)])


class _EmployeeFieldsMixin:
    """Fields shared by employee create and update forms.

    ``department_id`` choices are not known statically (they depend on
    the caller's organization/managed departments), so the route
    populates ``form.department_id.choices`` before validating.
    """

    department_id = SelectField("Department", coerce=int, validators=[DataRequired()])
    employee_number = StringField(
        "Employee number", validators=[DataRequired(), Length(max=100)]
    )
    first_name = StringField("First name", validators=[DataRequired(), Length(max=255)])
    last_name = StringField("Last name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[Optional(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    # 'terminated' is deliberately not offered here: that transition only
    # happens through the dedicated terminate action, which sets
    # terminated_on in the same step to satisfy the DB CHECK constraint.
    employment_status = SelectField(
        "Employment status",
        choices=[("active", "Active"), ("inactive", "Inactive")],
        validators=[DataRequired()],
    )
    weekly_contract_hours = OptionalDecimalField(
        "Weekly contract hours",
        places=2,
        validators=[Optional(), NumberRange(min=Decimal("0"), max=Decimal("168"))],
    )


class EmployeeCreateForm(_EmployeeFieldsMixin, FlaskForm):
    hired_on = DateField("Hired on", validators=[DataRequired()])


class EmployeeUpdateForm(_EmployeeFieldsMixin, FlaskForm):
    pass


class TerminateEmployeeForm(FlaskForm):
    terminated_on = DateField("Terminated on", validators=[DataRequired()])


class ChangePasswordForm(FlaskForm):
    """Self-service: the signed-in user changes their own password.
    Requires the current password (see ``auth.service.change_password``
    for why). Same 12-character minimum as
    ``CreateEmployeeAccountForm`` — one consistent policy for every
    password this application ever sets.
    """

    current_password = PasswordField(
        "Current password", validators=[DataRequired(), Length(max=255)]
    )
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=12, max=255)]
    )
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )


class AdminResetPasswordForm(FlaskForm):
    """Admin-only: reset a locked-out employee's password directly, since
    there is no email-sending capability in this application for a
    self-service "forgot password" link. Same 12-character minimum as
    every other password this application sets.
    """

    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=12, max=255)]
    )
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )


class UpdateOwnContactForm(FlaskForm):
    """Self-service: an employee editing their own contact info. Only
    ``phone`` — MVP-1_version2.md §7 names phone/personal contact info
    as employee-controlled; email is left out here since ``Employee.
    email`` is HR contact info while the *login* email lives on the
    separate ``User`` row, and conflating the two in one self-edit form
    risks an employee thinking they've changed their sign-in address
    when they haven't.
    """

    phone = StringField("Phone", validators=[Optional(), Length(max=50)])


class CreateEmployeeAccountForm(FlaskForm):
    """Admin-only: create the login account for an employee who does not
    yet have one. No format validator on ``email`` — same convention as
    ``LoginForm`` (format doesn't matter here either, only whether the
    address later works to sign in, and the ``email_validator`` package
    this would need isn't a project dependency).
    """

    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    # 12 characters is a reasonable modern minimum (security.md: "prefer
    # secure defaults") — there was no existing password-length policy
    # to preserve, since no account-creation path existed before this.
    password = PasswordField(
        "Initial password", validators=[DataRequired(), Length(min=12, max=255)]
    )


# HTML's datetime-local input has no timezone concept at all: whatever it
# submits is naive wall-clock time, interpreted by the service as local
# time in the organization's timezone (see app.services.scheduling).
_DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]


class _ShiftFieldsMixin:
    """Fields shared by shift create and update forms.

    ``department_id`` choices are populated by the route from the
    caller's visible departments, same pattern as
    ``_EmployeeFieldsMixin.department_id``.
    """

    department_id = SelectField("Department", coerce=int, validators=[DataRequired()])
    starts_at = DateTimeLocalField(
        "Starts at", format=_DATETIME_LOCAL_FORMATS, validators=[DataRequired()]
    )
    ends_at = DateTimeLocalField(
        "Ends at", format=_DATETIME_LOCAL_FORMATS, validators=[DataRequired()]
    )
    break_minutes = IntegerField(
        "Break minutes",
        default=0,
        # Upper bound matches the 24-hour shift/entry duration cap
        # enforced by the DB elsewhere (see migration 0008/0009's
        # duration_max_24_hours CHECKs) — without one, a value large
        # enough to overflow the SmallInteger column raises an unhandled
        # DataError instead of this field-level message (security-review
        # finding).
        validators=[Optional(), NumberRange(min=0, max=1440)],
    )
    notes = StringField("Notes", validators=[Optional(), Length(max=2000)])


class ShiftCreateForm(_ShiftFieldsMixin, FlaskForm):
    # 0 is the "unassigned" sentinel — no real employee id is ever 0 — so
    # a plain `coerce=int` SelectField can represent "no employee" without
    # needing a separate Optional() field type.
    employee_id = SelectField(
        "Employee", coerce=int, default=0, validators=[Optional()]
    )


class ShiftUpdateForm(_ShiftFieldsMixin, FlaskForm):
    # employee_id is deliberately absent: reassignment always goes through
    # the dedicated assign action (AssignEmployeeForm), never a generic
    # field edit — see app.services.scheduling.update_shift.
    pass


class AssignEmployeeForm(FlaskForm):
    employee_id = SelectField("Employee", coerce=int, validators=[DataRequired()])


class ClockInForm(FlaskForm):
    """Self-service clock-in: no fields beyond CSRF — always "now", always
    the caller's own employee record. See ``AdminClockInForm`` for the
    admin/manager variant with the extra fields those roles may use.
    """


class AdminClockInForm(ClockInForm):
    """Adds the fields only admin/manager may use: clocking in a
    different employee, and/or backdating the clock-in time.

    0 is the "myself" sentinel, matching the "0 means not otherwise
    specified" convention already used by ``ShiftCreateForm.employee_id``
    — no real employee id is ever 0.
    """

    employee_id = SelectField(
        "Employee", coerce=int, default=0, validators=[Optional()]
    )
    at = DateTimeLocalField(
        "Clock-in time (leave blank for now)",
        format=_DATETIME_LOCAL_FORMATS,
        validators=[Optional()],
    )


class ClockOutForm(FlaskForm):
    """Self-service clock-out: no fields beyond CSRF — always "now"."""


class AdminClockOutForm(ClockOutForm):
    """Adds the backdated clock-out time only admin/manager may set."""

    at = DateTimeLocalField(
        "Clock-out time (leave blank for now)",
        format=_DATETIME_LOCAL_FORMATS,
        validators=[Optional()],
    )


class _LeaveRequestFieldsMixin:
    """Fields shared by the self-service and admin/manager leave-request
    forms. ``leave_type_id`` choices are not known statically (they
    depend on the caller's organization), so the route populates
    ``form.leave_type_id.choices`` before validating — same pattern as
    ``_ShiftFieldsMixin.department_id``.
    """

    leave_type_id = SelectField(
        "Leave type", coerce=int, validators=[DataRequired()]
    )
    starts_at = DateTimeLocalField(
        "Starts at", format=_DATETIME_LOCAL_FORMATS, validators=[DataRequired()]
    )
    ends_at = DateTimeLocalField(
        "Ends at", format=_DATETIME_LOCAL_FORMATS, validators=[DataRequired()]
    )
    reason = StringField("Reason", validators=[Optional(), Length(max=2000)])


class LeaveRequestForm(_LeaveRequestFieldsMixin, FlaskForm):
    """Self-service leave request: always for the caller's own record."""


class AdminLeaveRequestForm(_LeaveRequestFieldsMixin, FlaskForm):
    """Adds the field only admin/manager may use: requesting leave on
    behalf of a different employee. 0 is the "myself" sentinel, matching
    the convention already used by ``AdminClockInForm.employee_id``.
    """

    employee_id = SelectField(
        "Employee", coerce=int, default=0, validators=[Optional()]
    )


class ApproveLeaveForm(FlaskForm):
    decision_note = StringField("Note (optional)", validators=[Optional(), Length(max=2000)])


class RejectLeaveForm(FlaskForm):
    """Rejecting a request always requires a reason — see
    ``app.services.leave.reject_leave``.
    """

    decision_note = StringField(
        "Reason for rejection", validators=[DataRequired(), Length(max=2000)]
    )


class CancelLeaveForm(FlaskForm):
    """No fields beyond CSRF — cancellation needs no extra input."""


class SetPayRateForm(FlaskForm):
    """Admin-only: record a new effective-dated hourly rate for an
    employee. ``places=4`` matches the DB's ``NUMERIC(10, 4)`` column so
    the value round-trips exactly.
    """

    hourly_rate = DecimalField(
        "Hourly rate",
        places=4,
        # Upper bound matches the DB's NUMERIC(10, 4) column exactly —
        # without one, a value large enough to overflow it raises an
        # unhandled DataError instead of this field-level message
        # (security-review finding).
        validators=[
            DataRequired(),
            NumberRange(min=Decimal("0.0001"), max=Decimal("999999.9999")),
        ],
    )
    effective_from = DateField("Effective from", validators=[DataRequired()])
    effective_to = DateField(
        "Effective to (leave blank if ongoing)", validators=[Optional()]
    )


class CorrectEntryForm(FlaskForm):
    """Admin/manager-only correction of an attendance entry's times.

    ``edit_reason`` is required (not optional) — see
    ``app.services.attendance.correct_entry``, the only place these
    corrections may be applied.
    """

    started_at = DateTimeLocalField(
        "Started at", format=_DATETIME_LOCAL_FORMATS, validators=[Optional()]
    )
    ended_at = DateTimeLocalField(
        "Ended at", format=_DATETIME_LOCAL_FORMATS, validators=[Optional()]
    )
    break_minutes = IntegerField(
        "Break minutes", validators=[Optional(), NumberRange(min=0, max=1440)]
    )
    edit_reason = StringField(
        "Reason for edit", validators=[DataRequired(), Length(max=2000)]
    )
