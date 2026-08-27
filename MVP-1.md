# Workforce Management Platform — MVP 1

> Status: Active Development
> Product: Workforce Management System
> Stack: Flask · PostgreSQL · HTML · CSS · JavaScript
> Product Inspiration: Modern Workforce Management platforms such as Quinyx
> Current Priority: Build one excellent page at a time, starting with the Admin Dashboard.

---

# 1. PRODUCT VISION

Build a professional, secure, maintainable Workforce Management Platform for a real company.

The system should manage:

- Employees
- User accounts
- Roles and permissions
- Departments
- Schedules
- Check-in / Check-out
- Breaks
- Attendance
- Working hours
- Overtime
- Leave
- Labor costs
- Reports
- Audit logs

The product is inspired by the workflow and product concepts of modern Workforce Management platforms such as Quinyx.

This is inspiration only.

Do NOT copy:

- Quinyx branding
- Quinyx logo
- Proprietary assets
- Exact UI
- Proprietary source code
- Proprietary implementation
- Exact visual identity

Create an original product with a comparable level of usability and professionalism.

---

# 2. PRODUCT PHILOSOPHY

This is NOT a generic CRUD dashboard.

The application should feel like a real workforce-management product that a company could use every day.

Prioritize:

1. Correct business logic
2. Security
3. Data integrity
4. Excellent UX
5. Professional visual design
6. Accessibility
7. Responsive behavior
8. Maintainability
9. Performance
10. Extensibility

Do not optimize for the amount of code produced.

Optimize for the quality of the product.

> Build less, but build it properly.

---

# 3. USER ROLES

The system must support authenticated users.

Primary roles:

| Role | Responsibility |
|------|----------------|
| ADMIN | Full organization management |
| MANAGER | Manage authorized employees and teams |
| EMPLOYEE | Personal workforce self-service |

Every employee must have a real authenticated account.

Conceptually:

~~~text
User
├── Authentication
├── Role
└── Employee
    ├── Schedule
    ├── Attendance
    ├── Work Sessions
    ├── Breaks
    ├── Leave
    └── Worked Hours
~~~

## Security Rules

- Authentication MUST be secure.
- Authorization MUST be enforced server-side.
- Never rely on hiding UI elements for authorization.
- Employees MUST NOT access admin endpoints.
- Managers MUST NOT automatically receive Admin privileges.
- Passwords MUST never be stored in plaintext.
- Secrets MUST never be committed to source control.
- Validate all user-controlled input.
- Use parameterized database queries.
- Protect state-changing operations against CSRF where applicable.
- Never expose stack traces or sensitive internal errors to users.

---

# 4. CORE WORKFORCE WORKFLOW

The fundamental workflow is:

~~~text
Employee Account
       │
       ▼
   Schedule
       │
       ▼
   Check In
       │
       ▼
    Working
       │
       ├──────► Start Break
       │             │
       │             ▼
       │           Break
       │             │
       │             ▼
       │           Working
       │
       ▼
  Check Out
       │
       ▼
 Worked Hours
       │
       ├──────► Overtime
       ├──────► Variance
       └──────► Labor Cost
~~~

The system must treat attendance as a real business workflow, not merely a CRUD operation.

---

# 5. CHECK-IN / CHECK-OUT

Check-in and check-out are critical MVP functionality.

The system should maintain clear attendance states:

~~~text
NOT_WORKING
     │
     │ CHECK IN
     ▼
WORKING
     │
     │ START BREAK
     ▼
ON_BREAK
     │
     │ END BREAK
     ▼
WORKING
     │
     │ CHECK OUT
     ▼
COMPLETED
~~~

Prevent invalid state transitions.

Examples:

- Cannot check in twice.
- Cannot check out without an active session.
- Cannot start multiple simultaneous breaks.
- Cannot end a nonexistent break.
- Cannot create overlapping work sessions.

The server/database is the source of truth.

The browser timer is only a presentation mechanism.

Never trust client-side time calculations as authoritative attendance data.

---

# 6. ATTENDANCE DATA
Prefer auditable attendance records.

Conceptually:

~~~text
AttendanceSession
├── id
├── employee_id
├── started_at
├── ended_at
├── status
├── source
├── created_at
└── updated_at
~~~

And:

~~~text
BreakSession
├── id
├── attendance_session_id
├── started_at
└── ended_at
~~~

Do NOT use a mutable value such as:

~~~python
employee.total_hours
~~~

as the authoritative source of attendance.

Worked time should be derived from authoritative records:

~~~text
Worked Time
=
Clock Out
-
Clock In
-
Break Duration
~~~

Preserve the underlying records so they can support:

- Auditing
- Recalculation
- Corrections
- Reports
- Labor-cost calculations
- Future payroll integrations

---

# 7. SCHEDULED VS ACTUAL HOURS

The system must connect schedules with actual attendance.

Example:

~~~text
Scheduled
09:00 ───────────────── 17:00

Actual
08:57 ───────────────────── 17:21
~~~

The system should be capable of calculating:

- Scheduled Hours
- Actual Hours
- Late Time
- Overtime
- Variance
- Labor Cost

Example:

~~~text
Scheduled Hours : 8h
Actual Hours    : 7h 54m
Late Time       : 0m
Overtime        : 21m
Variance        : -6m
~~~

Do not hard-code dashboard numbers for demonstration purposes.

Use real backend data whenever the required data exists.

---

# 8. EMPLOYEE EXPERIENCE

Employees are first-class users.

The employee area should eventually include:

~~~text
Employee
│
├── Dashboard
├── My Schedule
├── My Attendance
├── My Hours
├── Leave
└── Profile
~~~

The employee dashboard should immediately answer:

- What is my shift today?
- Am I currently working?
- When did I check in?
- How long have I worked?
- Am I currently on break?
- How many hours have I worked this week?
- What are my upcoming shifts?
- What is my recent attendance?

The Check-In / Check-Out interaction must be extremely clear and usable, especially on mobile.

---

# 9. ADMIN EXPERIENCE

The Admin area should eventually include:

~~~text
Admin
│
├── Dashboard
├── Employees
├── Departments
├── Schedule
├── Attendance
├── Leave
├── Working Hours
├── Labor Cost
├── Reports
└── Audit Log
~~~

The Admin Dashboard should answer:

> "What is happening with the workforce right now?"

Useful information includes:

- Total employees
- Currently working
- Late employees
- Absent employees
- Employees on leave
- Scheduled hours
- Actual hours
- Overtime
- Labor cost
- Attendance trends
- Employees requiring attention
- Recent activity

Do NOT turn every metric into a card.

Use the appropriate visualization for each type of information.

---

# 10. MANAGER EXPERIENCE

Managers should have controlled access to their workforce.

The architecture should be capable of supporting:

~~~text
Organization
│
├── Department
│      └── Team
│
└── Location
~~~

MVP 1 may use a simpler organizational structure, but avoid architectural decisions that make future expansion difficult.

Managers must only access resources within their authorized scope.

---

# 11. LEAVE MANAGEMENT

Basic leave workflow:

~~~text
Employee
    │
    │ Submit
    ▼
 PENDING
    │
    ├─────────────┐
    ▼             ▼
 APPROVED      REJECTED
~~~

Rules:

- Employees can create their own requests.
- Employees can see their own requests.
- Managers/Admins can review according to permissions.
- Approved leave must be reflected in appropriate workforce views.
- Rejected leave must not behave as approved leave.
- Prevent contradictory scheduling/leave states where appropriate.

---

# 12. MVP 1 BOUNDARIES

## In Scope

- Authentication
- User accounts
- Roles
- Employees
- Admin Dashboard
- Employee Dashboard
- Scheduling
- Check-in
- Check-out
- Breaks
- Attendance
- Working hours
- Overtime
- Leave
- Labor cost
- Basic reports
- Audit logging
- Responsive UI
- Secure architecture

## Out of Scope Unless Explicitly Requested
- AI forecasting
- Automatic schedule optimization
- Payroll integrations
- RFID terminals
- Advanced geofencing
- Offline mobile synchronization
- Advanced labor-law engines
- Demand forecasting
- Enterprise integrations
- Advanced shift marketplace
- Complex AI functionality

Keep the architecture extensible, but do not implement unnecessary future features now.

---

# 13. DESIGN DIRECTION

The application must look:

- Modern
- Minimal
- Professional
- Premium
- Calm
- Precise
- Data-driven
- Operational

The visual reference provided by the user is a design-language reference, not a template to copy.

Extract principles such as:

- Thin hairline borders
- Restrained neutral palette
- Opacity-based hierarchy
- Subtle dashed-grid details
- Strong typography
- Thin icons
- Generous whitespace
- Controlled information density
- Subtle animation
- Strong visual rhythm

Create an original design system suitable for a workforce-management product.

Do NOT copy another website literally.

---

# 14. AVOID GENERIC AI-GENERATED UI

Do NOT produce interfaces that look like generic AI-generated dashboards.

Avoid:

- Excessive cards
- Excessive rounded rectangles
- Random gradients
- Huge hero sections
- Unnecessary illustrations
- Excessive glassmorphism
- Excessive shadows
- Random colors
- Excessive animations
- Decorative elements without purpose
- Generic Bootstrap appearance
- Generic admin-template layouts
- Repetitive identical cards

Every visual element must have a purpose.

Prefer:

- Strong typography
- Good spacing
- Subtle borders
- Meaningful hierarchy
- Controlled color
- Data density where appropriate
- Consistent iconography
- Clear interaction states
- Excellent alignment

---

# 15. DESIGN SYSTEM

Create reusable design tokens and components.

The design system should define:

- Colors
- Typography
- Spacing
- Borders
- Radii
- Shadows
- Transitions
- Focus states
- Status colors
- Component states

Use a small, deliberate visual vocabulary.

Do not create a different visual language for every page.

All pages should feel like one coherent product.

---

# 16. COMPONENT PRINCIPLES

Create reusable components where repetition actually exists.

Examples:

~~~text
Button
Input
Select
FormField
Badge
StatusBadge
Card
Metric
Table
Pagination
Modal
Dropdown
Toast
EmptyState
LoadingState
ErrorState
ConfirmDialog
Navigation
Sidebar
Topbar
~~~

Do not abstract components merely because abstraction sounds cleaner.

Avoid premature abstraction.

Reusable components must remain simple and composable.

---

# 17. PAGE-BY-PAGE DEVELOPMENT

> CRITICAL: Build one major page at a time.

Do NOT build every page first and then attempt to fix the design.

Use this workflow:

~~~text
Understand
    ↓
Plan
    ↓
Design
    ↓
Implement
    ↓
Test
    ↓
Visual Review
    ↓
Refine
    ↓
Approve
    ↓
Next Page
~~~

A page is not complete simply because its backend works.

A page is complete only when:

~~~text
Functionality
+
UX
+
Visual Design
+
Responsive Design
+
Accessibility
+
Error States
+
Maintainability
~~~

meet the quality standard.

---

# 18. DEVELOPMENT ORDER

## Phase 1 — Admin Dashboard

This is the first visual and product-quality benchmark.

Focus deeply on:

- Information architecture
- Workforce overview
- Current attendance
- Scheduled vs actual hours
- Overtime
- Labor cost
- Employees requiring attention
- Recent activity
- Filters
- Responsive behavior
- Loading states
- Empty states
- Error states
- Accessibility
- Micro-interactions
- Typography
- Spacing
- Visual hierarchy

Do not rush this page.

It should establish the visual language that later pages reuse.

After completing the Admin Dashboard:

> STOP AND WAIT FOR REVIEW.

---

## Phase 2 — Employee Dashboard

Focus on:

- Today's shift
- Current status
- Check-in
- Check-out
- Breaks
- Worked time
- Weekly hours
- Upcoming shifts
- Recent attendance

---

## Phase 3 — Attendance

Focus on:

- Current status
- Attendance history
- Work sessions
- Breaks
- Scheduled vs actual
- Late arrivals
- Overtime
- Filtering
- Date ranges

---
## Phase 4 — Schedule

Focus on:

- Daily schedule
- Weekly schedule
- Employee assignment
- Shift information
- Schedule status
- Responsive schedule visualization

---

## Phase 5 — Leave

Focus on:

- Request creation
- Pending requests
- Approval
- Rejection
- History
- Status visibility

---

## Phase 6 — Employees

Focus on:

- Employee list
- Employee profile
- Account status
- Role
- Department
- Schedule relationship
- Attendance relationship

---

## Phase 7 — Working Hours & Labor Cost

Focus on:

- Actual hours
- Scheduled hours
- Variance
- Overtime
- Hourly cost
- Labor cost
- Date filtering
- Department/team breakdown

---

## Phase 8 — Reports

Build useful operational reports, not decorative charts.

---

## Phase 9 — Audit & Hardening

Focus on:

- Security
- Authorization
- Audit logs
- Edge cases
- Error handling
- Performance
- Accessibility
- Data integrity

---

# 19. VISUAL QUALITY GATE

Every major page must pass a visual review.

Check:

| Area | Requirement |
|------|-------------|
| Hierarchy | Clear primary → secondary → tertiary information |
| Typography | Consistent and readable |
| Spacing | Deliberate and consistent |
| Layout | Strong composition |
| Color | Restrained and meaningful |
| Icons | Consistent icon language |
| States | Loading / Empty / Error / No Results |
| Interaction | Hover / Focus / Active states |
| Responsive | Desktop / Tablet / Mobile |
| Accessibility | Keyboard / Contrast / Semantics |

If the result looks generic:

> STOP AND REFINE.

Do not move to the next page merely because the functionality works.

---

# 20. RESPONSIVE DESIGN

Do not simply shrink desktop layouts.

## Desktop

Prioritize:

- Information density
- Multi-column layouts
- Tables
- Analytics
- Workforce overview

## Tablet

Prioritize:

- Reduced density
- Adaptive navigation
- Reorganized layouts

## Mobile

Prioritize:

- Primary actions
- Employee clocking
- Essential information
- Touch-friendly controls
- Readable data

Check-in / Check-out must remain extremely easy to use on mobile.

---

# 21. ACCESSIBILITY

Follow WCAG principles.

At minimum:

- Semantic HTML
- Keyboard navigation
- Visible focus states
- Sufficient contrast
- Accessible labels
- Accessible form errors
- Accessible buttons
- Reduced-motion support
- Screen-reader-friendly status information
- Do not rely on color alone to communicate state

Accessibility is part of implementation, not a final cosmetic pass.

---

# 22. SECURITY

Security is a first-class requirement.

Use secure-by-default engineering.

Required principles:

- Secure password hashing
- Secure session handling
- Server-side authorization
- CSRF protection where applicable
- Strict validation
- Output escaping
- Parameterized SQL
- Safe error handling
- Environment-based secrets
- No secrets in Git
- Secure file handling
- Appropriate audit logging

When adding new functionality, actively look for:

- Broken access control
- IDOR-style vulnerabilities
- Missing authorization checks
- SQL injection
- XSS
- CSRF
- Session problems
- Unsafe file uploads
- Sensitive data exposure
- Race conditions in attendance operations

Never weaken security simply to make development easier.

---

# 23. DATA INTEGRITY

Workforce data may affect payroll and money.

Treat it as financial-grade business data.

Therefore:

- Use database constraints.
- Use foreign keys.
- Use unique constraints where required.
- Prevent duplicate check-ins.
- Prevent invalid check-outs.
- Prevent impossible break states.
- Validate state transitions.
- Use transactions for multi-step operations.
- Preserve auditability.
- Define timezone behavior explicitly.
- Do not blindly trust client-provided timestamps.

---

# 24. ARCHITECTURE

The application should remain maintainable for years.

Prefer separation such as:

~~~text
Routes / Controllers
        ↓
Services / Business Logic
        ↓
Data Access
        ↓
Models / Database
~~~

Keep appropriately separated:

- Authentication
- Authorization
- Validation
- Business logic
- Data access
- Presentation

Avoid:
- Giant route files
- Spaghetti code
- Duplicated business logic
- Magic numbers
- Hard-coded business rules
- Duplicated CSS
- Tight coupling
- Unnecessary rewrites
- Over-engineering

Follow the existing architecture when it is sound.

Do not rewrite working functionality simply to introduce a fashionable architecture.

---

# 25. POSTGRESQL

PostgreSQL is the authoritative relational data store.

Use appropriate:

- Primary keys
- Foreign keys
- Unique constraints
- Indexes
- NOT NULL constraints
- Timestamps
- Transactions

Avoid unnecessary denormalization.

Derived values should generally be calculated from authoritative records rather than maintained as independent sources of truth.

---

# 26. TESTING

Testing must be risk-based.

## Highest Priority

Thoroughly test:

- Authentication
- Authorization
- Check-in
- Check-out
- Breaks
- Work-hour calculations
- Overtime
- Leave approval
- Labor-cost calculations
- Database state transitions

## Medium Priority

- Reports
- Filters
- Employee management
- Scheduling

## Lower Priority

- Pure visual CSS changes

Do not run enormous test suites after every tiny CSS modification unless necessary.

Prefer:

~~~text
Small Change
    ↓
Focused Test
    ↓
Continue

Major Feature
    ↓
Feature Tests
    ↓
Broader Regression Tests
~~~

Tests should validate real behavior.

Do not create fake tests merely to increase test counts.

---

# 27. ERROR HANDLING

Important operations must have explicit failure behavior.

Examples:

- Failed check-in
- Failed check-out
- Unauthorized action
- Expired session
- Network failure
- Validation failure
- Database failure
- Invalid state transition

User-facing errors should be understandable.

Never expose:

- Stack traces
- SQL errors
- Database internals
- Secrets
- Internal implementation details

to normal users.

---

# 28. AUDITABILITY

Sensitive administrative operations should be auditable.

Audit events may include:

~~~text
User
Action
Target
Timestamp
Relevant Metadata
~~~

Never store passwords, tokens, or credentials in audit logs.

---

# 29. PERFORMANCE

Avoid obvious performance problems.

Pay attention to:

- N+1 queries
- Unnecessary database requests
- Unnecessary API calls
- Unnecessary client-side calculations
- Oversized assets
- Excessive JavaScript
- Unnecessary dependencies

Use pagination for potentially large datasets.

Do not prematurely optimize everything.

---

# 30. DOCUMENTATION

Keep documentation concise and accurate.

Document:

- Setup
- Architecture
- Environment variables
- Database
- Authentication
- Authorization
- Major workflows
- Deployment
- Testing

Documentation must describe the actual implementation.

Never document functionality that does not exist.

---

# 31. SUBAGENT POLICY

> Subagents are an exception, not the default workflow.

The primary Claude session should perform normal implementation work.

## Do NOT spawn subagents for:

- Simple CSS
- One page
- Small refactoring
- Simple CRUD
- Reading small files
- Routine tests
- Minor bug fixes
- Normal implementation

## Use a subagent only when there is clear independent value.

Good use cases:

1. Complex security review
2. Large architectural investigation
3. Independent review of a completed major feature
4. Large codebase exploration where isolated context is genuinely useful

## Default

| Task | Subagents |
|------|-----------:|
| Normal feature | 0 |
| Normal page | 0 |
| Small refactor | 0 |
| Major feature | 0–1 |
| Security review | 1 |
| Milestone review | 1 |

Do NOT create chains of agents.

Do NOT use multiple agents to review the same small task.

> The goal is quality, not agent count.

---

# 32. REVIEWER AGENT

The Reviewer Agent is a milestone reviewer, not a permanent worker.

Use it after a significant feature is complete.

Review:

- Correctness
- Security
- Authorization
- Architecture
- Maintainability
- Edge cases
- Accessibility
- Tests
- Performance risks

The Reviewer must produce:

~~~text
## Critical

...

## High

...

## Medium

...

## Low

...

## Good

...

## Recommendation

...
~~~
The Reviewer should NOT rewrite large parts of the project.

The primary Claude session decides which findings to fix.

---

# 33. VISUAL REVIEW

Do not claim a page is complete merely because:

- CSS compiles
- HTTP returns 200
- Templates render
- Tests pass

When visual tooling is available, inspect the actual rendered page.

Review:

- Composition
- Spacing
- Typography
- Hierarchy
- Color
- Density
- Interaction states
- Responsive behavior
- Accessibility

If visual quality is poor:

> REFINE BEFORE MOVING FORWARD.

---

# 34. IMPLEMENTATION DISCIPLINE

Before changing code:

1. Inspect the existing implementation.
2. Understand the architecture.
3. Identify dependencies.
4. Identify risks.
5. Define the smallest coherent change.
6. Implement.
7. Run focused tests.
8. Inspect the result.
9. Refine if necessary.
10. Update documentation when required.

Do not make broad changes without understanding the existing codebase.

Do not introduce unnecessary dependencies.

Do not rewrite working functionality without a concrete reason.

---

# 35. DEFINITION OF DONE

A feature is DONE only when the relevant criteria are satisfied:

~~~text
┌───────────────────────────────┐
│       DEFINITION OF DONE      │
├───────────────────────────────┤
│ ✓ Business behavior works     │
│ ✓ Authorization is correct    │
│ ✓ Validation exists           │
│ ✓ Errors are handled          │
│ ✓ Edge cases considered       │
│ ✓ Relevant tests pass         │
│ ✓ Responsive behavior works   │
│ ✓ Accessibility is acceptable │
│ ✓ Visual quality is strong    │
│ ✓ Code is maintainable        │
│ ✓ Documentation is accurate   │
└───────────────────────────────┘
~~~

Do not mark a feature complete because "the code works".

---

# 36. CURRENT MISSION — ADMIN DASHBOARD

The immediate mission is:

> Build the Admin Dashboard to a professional production-quality standard.

Do not immediately implement every page.

Spend the necessary effort on:

- Information architecture
- Workforce overview
- Attendance state
- Scheduled vs actual hours
- Overtime
- Labor cost
- Employees requiring attention
- Recent activity
- Filters
- Responsive behavior
- Loading states
- Empty states
- Error states
- Accessibility
- Micro-interactions
- Typography
- Spacing
- Visual hierarchy

The result should feel like:

> A real workforce-management product used by a serious company.

It must NOT feel like:

> A Flask CRUD application with some CSS.

---

# 37. STOP CONDITION

After completing the Admin Dashboard:

STOP.

Do not automatically continue to another page.

Report:

1. Files changed
2. Components created
3. Components reused
4. Backend data used
5. Design decisions
6. Responsive decisions
7. Accessibility checks
8. Tests performed
9. Security considerations
10. Remaining issues
11. Reusable design patterns
12. Recommended improvements

Then wait for approval.

---

# 38. FINAL ENGINEERING PRINCIPLES

> Quality over speed.

> Product thinking over CRUD thinking.

> Security over convenience.

> Real data over fake data.

> Reusable patterns over duplicated code.

> One excellent page at a time.

> Subagents only when they provide real independent value.

> Do not move forward when the current page is visually or technically weak.

The ultimate goal is to create a:

Professional + Secure + Maintainable + Responsive + Accessible Workforce Management Platform

that is suitable for delivery to a real company and capable of evolving beyond MVP 1 into a production system.

