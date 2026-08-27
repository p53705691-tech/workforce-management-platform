# MVP 1 — Final System Audit & Hardening

## Role

You are the Lead Engineer and Final Auditor for the current MVP 1.

Your responsibility is to review the real codebase, evaluate the independent audit reports, verify their findings, fix confirmed issues, and establish a reliable baseline for future development.

---

## Scope

Audit ONLY the currently implemented MVP 1.

Do NOT:

- Start MVP 2
- Start MVP 3
- Add AI features
- Add new product features
- Rewrite working architecture unnecessarily
- Change business rules without evidence
- Modify unrelated functionality

---

## Phase 1 — Understand the System

Inspect the actual codebase before making changes.

Review:

- Architecture
- Routes
- Services
- Models
- Database constraints
- Authentication
- Authorization
- Templates
- Forms
- Configuration
- Tests
- Existing documentation
- Design system

The actual implementation is the source of truth.

Do not blindly trust documentation.

---

## Phase 2 — Review Independent Audits

Three independent auditors will investigate:

1. Security
2. QA / Functional correctness
3. Data integrity / Business logic

They must investigate only and must NOT modify the code.

For every reported issue:

1. Verify it against the actual code.
2. Determine whether it is a real issue.
3. Determine severity.
4. Identify the root cause.
5. Implement the smallest appropriate fix.
6. Add a focused regression test where appropriate.
7. Run the relevant tests.

Do not blindly implement an auditor's recommendation.

---

## Critical Role Separation

Verify the complete separation between:

### ADMIN

Organization-level management and oversight.

### MANAGER

Authorized team/department workforce management.

### EMPLOYEE

Personal self-service.

Employee-only workflows such as:

- Clock In
- Clock Out
- My Attendance
- My Schedule
- Request Leave
- My Worked Hours

must not appear as management workflows for Admin/Manager.

Backend authorization must independently enforce every permission.

Never rely on UI visibility for security.

---

## Security Requirements

Pay special attention to:

- IDOR / BOLA
- Broken access control
- Privilege escalation
- Cross-department access
- Unauthorized direct URLs
- Employee-to-employee data access
- Sensitive labor-cost information
- Session/authentication security
- CSRF
- XSS
- SQL injection
- Input validation
- Production configuration
- Debug exposure
- Cache-Control for authenticated pages

Managers must never receive unauthorized individual employee pay/rate information.

---

## Functional Verification

Verify the complete workflows:

Admin creates employee
→ creates/assigns account
→ assigns department
→ assigns schedule
→ Employee logs in
→ Employee clocks in
→ Employee clocks out
→ Manager reviews attendance
→ Employee requests leave
→ Manager approves/rejects
→ Reports reflect the resulting data
→ Admin reviews audit activity

Also test invalid and unauthorized versions of these workflows.

---

## Data & Business Logic

Verify:

- Worked hours
- Break deductions
- Overtime
- Leave duration
- Labor cost
- Effective-dated rates
- Decimal precision
- Rounding
- Scheduling conflicts
- Department aggregation
- Date/time boundaries
- Midnight crossings
- Empty datasets
- Invalid states

Do not invent business rules.

---

## Responsive Verification

Verify the existing design at:

- 1440px
- 1024px
- 768px
- 390px
- 360px

Preserve ONE visual identity across all screen sizes.

Do not create a separate mobile visual design.

---

## Testing

Run the complete existing test suite.

Add only meaningful regression tests.

Do NOT:

- Delete failing tests to make the suite pass
- Create meaningless tests
- Duplicate existing coverage unnecessarily

After all fixes, run the complete test suite again.

---

## Change Policy

Prefer:

> Smallest safe fix > large refactor

Do not rewrite stable modules.

Do not introduce speculative architecture.

Do not modify the database unless genuinely necessary.

---

## Final Report

When finished, report:

### Fixed Issues

List confirmed issues and their fixes.
### Security

List security issues discovered and resolved.

### Tests

Provide before/after results.

### Changed Files

List only files actually modified.

### Remaining Issues

List only genuine unresolved issues or decisions requiring the user's input.

Never claim that something was tested or verified unless it was actually verified.
