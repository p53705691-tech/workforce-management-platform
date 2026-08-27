# Employee Experience & Role-Based Workforce UX — MVP 1

> Status: Active Development  
> Scope: Employee Experience + related role-specific workflows  
> Stack: Flask · PostgreSQL · SQLAlchemy · HTML · CSS · JavaScript  
> Architecture: Existing modular Flask application  
> Primary Goal: Build a production-quality Workforce Management platform with distinct, role-appropriate experiences for Admin, Manager, and Employee.  
> Design Goal: Modern, elegant, highly usable SaaS UX — not a generic CRUD dashboard.  
> Important: Work feature-by-feature. Do not redesign unrelated parts of the application.

---

# 1. CORE PRODUCT PRINCIPLE

The application has three primary roles:

                    WORKFORCE PLATFORM
                           │
             ┌─────────────┼─────────────┐
             │             │             │
           ADMIN        MANAGER       EMPLOYEE
             │             │             │
      Organization       Team Ops     Self-Service
      Configuration      Scheduling   Daily Work
      Users/Roles        Attendance   Check In/Out
      Employees          Leave        My Schedule
      Departments        Reports      My Hours
      Labor Cost         Team View    Requests
      Audit              Analytics    Profile

These are NOT three copies of the same dashboard.

Each role must have a different information hierarchy based on its responsibilities.

## ADMIN

The Admin experience is for:

- Organization management
- Employees
- User accounts
- Roles and permissions
- Departments
- Organization configuration
- Scheduling oversight
- Attendance oversight
- Leave management
- Labor costs
- Reports
- Audit logs

## MANAGER

The Manager experience is for:

- Team management
- Team scheduling
- Team attendance
- Leave approval
- Team working hours
- Team coverage
- Relevant reports
- Employees within the Manager's authorized scope

## EMPLOYEE

The Employee experience is for:

- Personal workday
- Check In / Check Out
- Today's shift
- My Schedule
- My Attendance
- My Hours
- Leave requests
- Personal requests
- Notifications
- Profile

The Employee interface must therefore feel like a dedicated self-service product, NOT like an Admin dashboard with menu items removed.

---

# 2. PRODUCT UX PRINCIPLE

The application should communicate a clear distinction:

ADMIN
Control + Configuration + Organization

MANAGER
Team Operations + Decisions

EMPLOYEE
Daily Work + Self-Service

The Employee should not need to understand:

- organization-wide labor costs
- audit logs
- role management
- department administration
- organization configuration
- workforce-wide reports

The Manager should not see information outside their authorization scope.

The Admin should have the broadest organizational visibility.

---

# 3. FEATURE OWNERSHIP RULE

A feature may have different interfaces for different roles.

When implementing or redesigning a feature:

1. Identify every role affected by the feature.
2. Improve only the relevant role-specific interfaces.
3. Reuse the same backend business logic.
4. Preserve centralized authorization.
5. Avoid duplicating business rules.
6. Do not redesign unrelated pages.

Example:

LEAVE
│
├── EMPLOYEE
│   ├── View balance
│   ├── Submit request
│   ├── View own requests
│   └── Cancel eligible request
│
├── MANAGER
│   ├── View team requests
│   ├── Approve
│   ├── Reject
│   └── View team leave
│
└── ADMIN
    ├── Organization-level management
    ├── Leave configuration
    ├── Policies
    └── Organization reporting

Another example:

EMPLOYEES
│
├── ADMIN / MANAGER
│   ├── Create employee
│   ├── Edit employee
│   ├── Assign department
│   ├── Assign manager
│   ├── Configure employment information
│   └── Create / invite employee account
│
└── EMPLOYEE
    ├── View own profile
    ├── Edit permitted personal information
    └── Manage own account

Do NOT isolate Employee development from the Admin/Manager workflows that make Employee functionality possible.
However, do NOT use an Employee task as an excuse to redesign unrelated Admin/Manager pages.

---

# 4. IMPLEMENTATION RULE — INSPECT BEFORE CHANGING

Before changing anything:

1. Inspect the existing codebase.
2. Inspect the current architecture.
3. Inspect existing routes.
4. Inspect existing services.
5. Inspect User and Employee models.
6. Inspect authentication.
7. Inspect authorization.
8. Inspect attendance.
9. Inspect scheduling.
10. Inspect leave.
11. Inspect working-hour calculations.
12. Inspect Admin/Manager employee creation.
13. Inspect existing CSS/design tokens/components.
14. Determine which functionality already exists.
15. Determine which functionality is missing.
16. Identify which parts can be reused.
17. Identify any backend gaps before designing UI around them.

Do NOT rebuild existing functionality merely because the UI is changing.

Do NOT create duplicate business logic.

Do NOT introduce a new architecture.

Do NOT replace existing authentication.

Do NOT replace existing authorization.

Do NOT invent backend capabilities that do not exist.

If something required by the UX does not exist in the backend, clearly report the gap before implementing a fake UI.

---

# 5. ACCOUNT AND EMPLOYEE MODEL

The intended workflow is:

ADMIN / MANAGER
       │
       ▼
Create Employee
       │
       ├── Employee information
       ├── Department
       ├── Position
       ├── Manager
       ├── Employment information
       └── Account / invitation
       │
       ▼
Employee account
       │
       ▼
Employee logs in
       │
       ▼
Dedicated Employee Portal

The company creates the employee.

The employee does NOT register themselves as a company employee.

This provides organizational control over:

- identity
- role
- department
- manager
- employment status
- account access
- workforce data

The employee may manage appropriate personal/account information after receiving access.

---

# 6. USER / EMPLOYEE RELATIONSHIP

Preserve the conceptual separation:

User
├── Authentication identity
├── Email / username
├── Password
├── Role
└── Account status
        │
        ▼
Employee
├── Personal information
├── Department
├── Position
├── Employment information
├── Schedule
├── Attendance
├── Leave
└── Worked hours

If the existing application already implements this relationship, reuse it.

Do not introduce duplicate user records.

Do not create a second authentication system.

Do not create a separate Employee authentication mechanism.

---

# 7. INFORMATION OWNERSHIP

Clearly distinguish company-controlled information from employee-controlled information.

## COMPANY-CONTROLLED INFORMATION

Examples:

- Employee ID
- Department
- Position
- Manager
- Employment type
- Start date
- Work location
- Pay configuration
- Overtime configuration
- Role
- Account permissions
- Employment status

Employees must not freely modify these.

## EMPLOYEE-CONTROLLED INFORMATION

Examples:

- Profile picture
- Phone number
- Appropriate personal contact information
- Password
- Notification preferences
- Other explicitly permitted personal fields

Do not invent sensitive personal fields.

Follow the existing product requirements and privacy model.

---

# 8. EMPLOYEE PORTAL NAVIGATION

Create a dedicated Employee navigation.

Recommended structure:

EMPLOYEE PORTAL
│
├── Home
├── My Schedule
├── Time & Attendance
├── My Hours
├── Leave
├── Requests
├── Notifications
└── My Profile

Keep this navigation intentionally small.

The Employee should not need to understand internal company administration.

The navigation should make the employee's daily workflow obvious.

---

# 9. EMPLOYEE HOME

The Employee Home page is the most important Employee page.

It should be exceptionally polished.

The primary information hierarchy should be:

1. Current work status
2. Check In / Check Out
3. Today's shift
4. Worked time
5. Upcoming schedule
6. Weekly hours
7. Important requests / notifications

The employee should understand their workday within seconds.

Suggested information architecture:

EMPLOYEE HOME
Good morning, [First Name]

TODAY
09:00 — 17:00

Current status:
Not started

[ CHECK IN ]

Today's shift
09:00 – 17:00
Location

Today's hours
Worked
Scheduled
Remaining

THIS WEEK
Mon   Tue   Wed   Thu   Fri
8h    7h    8h    8h    6h

UPCOMING
Tomorrow
09:00 – 17:00

IMPORTANT
Pending leave request

This is an information architecture reference only.

Create an original, polished design.

Do NOT blindly reproduce this layout.

---

# 10. CHECK IN / CHECK OUT

Check-in/out is the primary Employee interaction.

It must be:

- highly visible
- extremely easy to use
- obvious in its current state
- safe against accidental duplicate actions
- responsive
- accessible

Conceptually:

NOT_STARTED
     │
     ▼
  WORKING
     │
     ▼
 COMPLETED

If the backend supports breaks, represent them correctly.

If the backend currently only supports continuous work spans with flat break minutes, DO NOT invent a break state machine in the UI.

The UI must reflect the real backend.

If a required backend capability does not exist, identify the gap instead of faking functionality.

---

# 11. CHECK-IN UX

Before check-in:

Today's shift

09:00 — 17:00

Ready to start your shift?

[ Check In ]

After check-in:

You're working

Started at 08:57

02h 41m elapsed

[ Check Out ]

The interaction must include:

- loading state
- disabled state during submission
- success feedback
- error feedback
- protection against accidental duplicate submission
- keyboard accessibility
- mobile-friendly interaction

Use the existing attendance service.

Do not duplicate attendance logic in JavaScript or templates.

---

# 12. ATTENDANCE SECURITY

Employees may only access their own attendance.

Never trust an employee-supplied employee ID.

Authorization must happen server-side.

Prevent:

- IDOR
- cross-employee attendance access
- unauthorized correction
- manipulation of another employee's data
- duplicate attendance operations

Do not rely on hiding links.

The underlying service must enforce authorization.

---

# 13. WORKDAY STATUS

Status should be understandable without color alone.

Use:

- icon
- text
- subtle visual treatment

Example:

● Working
Started 08:57

Do not communicate state only through:

green = working
red = absent

Color should support meaning rather than be the only signal.

---

# 14. MY SCHEDULE

Create a dedicated Employee Schedule experience.

Employees should be able to see:

- today's shift
- upcoming shifts
- weekly schedule
- shift start/end
- location where applicable
- relevant schedule information

The purpose is:

> "When do I work?"

It should NOT look like the Admin scheduling interface.

Admin/Manager scheduling answers:

> "How do I manage workforce coverage?"

Employee scheduling answers:

> "When and where do I work?"

Use the same underlying schedule data and business rules.

Do not duplicate scheduling logic.

---

# 15. TIME & ATTENDANCE

Create an Employee-facing attendance history.

Show only the employee's own information.

Example:

THIS WEEK

Date        Scheduled       Worked        Status
Mon         09:00–17:00     7h 45m        Completed
Tue         09:00–17:00     8h 02m        Completed
Wed         10:00–18:00     7h 58m        Completed

Support:

- date range
- status
- loading
- empty
- error
- no-results
- responsive behavior

On mobile, transform dense tables into readable cards/list items where appropriate.

---

# 16. MY HOURS

Create a dedicated working-hours page.

Potential information:

THIS WEEK

Worked
38h 20m

Scheduled
40h

Difference
-1h 40m

Where the backend already supports it, show:

- today
- this week
- this month
- scheduled vs worked
- overtime

Do not expose hourly rate or labor-cost data to Employees unless explicitly required.

Employee hours are about their time.

Labor Cost is an administrative/managerial concern.

Use existing working-hour calculations.

Do not recreate calculations in the frontend.

---

# 17. LEAVE — EMPLOYEE

Employee Leave should allow:
- viewing leave balance where available
- viewing own requests
- creating a request
- viewing request status
- cancelling eligible requests

Example:

LEAVE

Available
12 days

Pending
1 request

Approved
8 days

[ Request Leave ]

Request form:

Leave type
Start date
End date
Reason

[ Submit request ]

Use real backend validation.

Never invent company leave policies.

If the existing backend does not support a requested feature, identify the gap instead of creating fake behavior.

---

# 18. LEAVE — MANAGER / ADMIN

If the existing Leave workflow is incomplete or visually weak, improve the relevant Manager/Admin parts required to make the Employee Leave workflow complete.

Manager:

- team requests
- approve
- reject
- team leave overview

Admin:

- organization-level leave management
- configuration
- policies if supported
- reporting if supported

Do not redesign unrelated Admin/Manager pages.

Only make the minimum role-specific changes necessary.

---

# 19. EMPLOYEE REQUESTS

If the existing backend supports multiple employee request types, provide a central request experience.

If only Leave currently exists:

DO NOT invent fake request types.

Keep the UI focused on real supported functionality.

Future request types can be added later.

---

# 20. NOTIFICATIONS

If a real notification backend exists, expose it.

If it does not exist:

DO NOT build fake notifications merely for visual appearance.

Instead, identify the backend gap and leave the architecture extensible for future notifications.

Potential real notifications include:

- shift changed
- leave approved
- leave rejected
- schedule reminder
- attendance issue
- company announcement

Only display notifications backed by real data.

---

# 21. EMPLOYEE PROFILE

Create a polished Employee Profile page.

Structure:

PROFILE
│
├── Personal Information
├── Contact Information
├── Employment Information
└── Account Settings

Clearly distinguish:

READ ONLY
vs.
EDITABLE

Example:

Employment

Department       Engineering      Read only
Position         Developer         Read only
Employee ID      EMP-1042         Read only

Personal

Phone            +...
Profile photo    [Change]

Never make company-controlled fields appear editable if they are not.

---

# 22. ADD EMPLOYEE — ADMIN / MANAGER

The Employee Portal depends on a good employee onboarding flow.

Review the existing Add Employee workflow.

If it is visually weak, confusing, incomplete, or incompatible with the Employee account model, improve it.

The flow should clearly support:

ADD EMPLOYEE
    │
    ├── Personal information
    ├── Employment information
    ├── Department
    ├── Position
    ├── Manager
    ├── Account access
    └── Review / Create

The exact fields must come from the existing domain model.

Do NOT invent unnecessary fields.

If the application already has a correct implementation, reuse it rather than rebuilding it.

---

# 23. ADMIN / MANAGER UX PRINCIPLE

Admin and Manager interfaces may remain operationally dense.

Employee interface should be lighter.

ADMIN
Control + Configuration + Analytics

MANAGER
Team Operations + Decisions

EMPLOYEE
Daily Work + Self-Service

Do not force all roles into the same UI structure.

The Admin/Manager UI and Employee UI should share the same design language, but NOT necessarily the same layout.

Think:

Same product
      │
      ├── Shared design system
      ├── Shared typography
      ├── Shared tokens
      ├── Shared components
      │
      ├── Admin experience
      ├── Manager experience
      └── Employee experience

---

# 24. VISUAL DESIGN

The Employee portal should feel:

- modern
- premium
- calm
- human
- lightweight
- fast
- highly readable
- mobile-first
- intentional

Use the existing design system as a foundation.

Maintain:

- typography
- spacing
- color tokens
- accessibility
- button styles
- form styles
- semantic status colors

But create a different composition for Employee pages.

Preferred characteristics:
- generous whitespace
- strong typography hierarchy
- restrained cards
- subtle borders
- elegant status indicators
- clear primary action
- minimal visual noise
- tasteful micro-interactions

Avoid:

- excessive gradients
- excessive glassmorphism
- huge rounded cards everywhere
- excessive shadows
- random colors
- excessive animations
- generic SaaS template appearance
- unnecessary decorative elements
- dashboard-card overload

The final result should look like a serious modern SaaS product.

---

# 25. DESIGN REFERENCES

Take inspiration from modern:

- Workforce Management products
- HR self-service applications
- scheduling platforms
- productivity applications
- modern SaaS systems

Quinyx may be used as a conceptual reference for workforce-management workflows.

DO NOT copy:

- Quinyx branding
- logos
- proprietary assets
- proprietary source code
- exact visual identity
- exact UI
- proprietary implementation

We want comparable usability and product maturity, not a clone.

The goal is to create an original product that could realistically be presented to a professional company.

---

# 26. ICON SYSTEM

Use a consistent icon system.

Prefer:

- Lucide
- inline SVG
- CSP-safe icons

Maintain:

- consistent stroke weight
- consistent sizing
- semantic usage

Do not add icons merely as decoration.

Icons should improve:

- navigation
- recognition
- status communication
- action discoverability

---

# 27. RESPONSIVE DESIGN

Employee UX must be excellent on:

- desktop
- laptop
- tablet
- mobile

Mobile is especially important because employees may access the portal primarily from their phones.

On mobile:

- navigation collapses elegantly
- Check In/Out remains highly accessible
- today's shift appears immediately
- cards stack naturally
- tables transform appropriately
- forms are touch-friendly
- buttons have appropriate touch targets
- no unnecessary horizontal scrolling

Do not simply shrink desktop layouts.

Design mobile intentionally.

---

# 28. ACCESSIBILITY

Follow WCAG-oriented practices.

Ensure:

- semantic HTML
- correct heading hierarchy
- keyboard navigation
- visible focus states
- sufficient contrast
- accessible labels
- accessible error messages
- status not communicated only by color
- reduced-motion support
- appropriate touch targets
- meaningful button labels

Accessibility is part of product quality.

---

# 29. PERFORMANCE

Employee Home will likely be visited frequently.

Avoid unnecessary:

- database queries
- duplicate service calls
- expensive calculations
- large JavaScript dependencies
- duplicate business logic
- unnecessary client-side rendering

Reuse existing services.

Do not introduce complexity without a reason.

Prefer server-rendered HTML where the current application architecture already uses it.

Do not introduce a frontend framework simply for the Employee portal unless there is a clear architectural reason.

---

# 30. SECURITY

Security is a first-class requirement.

For every Employee route:

- require authentication
- verify employee identity
- enforce authorization server-side
- prevent IDOR
- validate input
- preserve CSRF protection
- escape output
- protect sensitive information
- never trust client-side role data
- preserve secure authentication
- preserve password hashing
- preserve lockout behavior
- prevent unauthorized object access

An Employee must never access:

- another employee's attendance
- another employee's schedule
- another employee's leave
- labor costs
- hourly rates
- administrative reports
- organization-wide sensitive information
- Admin routes
- Manager routes

---

# 31. DATA INTEGRITY

Never bypass business rules through the UI.

Use existing services for:

- check-in
- check-out
- attendance
- schedule
- leave
- working hours
- employee account operations

Do not put business rules in Jinja.

Do not put business rules in JavaScript.

The service layer remains authoritative.

---

# 32. DATA STATES

Every important Employee page should intentionally handle:

LOADING
EMPTY
ERROR
UNAUTHORIZED
NO_RESULTS
SUCCESS
Example:
Unable to load your schedule.

Please try again.

[ Retry ]

Never expose:

- stack traces
- SQL errors
- internal exception messages
- sensitive debugging information

---

# 33. EMPTY STATES

Make empty states useful.

Example:

No upcoming shifts

You don't have any scheduled shifts yet.

[ View Schedule ]

Avoid generic:

No data.

Empty states should tell the employee:

1. What happened.
2. Whether action is required.
3. What they can do next.

---

# 34. MICRO-INTERACTIONS

Use animation carefully.

Good uses:

- Check-in success
- Check-out success
- subtle page entrance
- button loading
- navigation transitions
- status changes
- hover/focus feedback

Respect:

prefers-reduced-motion

Do not animate everything.

Animation must support usability rather than distract from it.

---

# 35. FEATURE-BY-FEATURE DEVELOPMENT

Do NOT redesign the entire application in one pass.

Work feature-by-feature.

Recommended order:

E1
Employee Account + Employee Home
        │
        ▼
E2
My Schedule
        │
        ▼
E3
Time & Attendance
        │
        ▼
E4
My Hours
        │
        ▼
E5
Leave
        │
        ▼
E6
Requests / Notifications
        │
        ▼
E7
Profile

For each feature, update only the relevant Admin/Manager workflow if necessary.

Example:

Employee Leave
        │
        ├── Employee Leave UI
        └── Manager Leave approval UI

Do not touch unrelated areas.

---

# 36. EMPLOYEE HOME FIRST

Start with Employee Home only.

Before coding:

1. Inspect the existing codebase.
2. Identify existing Employee routes.
3. Identify existing Employee services.
4. Identify existing attendance functionality.
5. Identify existing schedule functionality.
6. Identify existing employee account creation.
7. Identify existing reusable components.
8. Identify backend gaps.
9. Propose the page structure.
10. Implement Employee Home.

Then:

- run relevant tests
- verify authorization
- verify functionality
- verify responsive behavior
- verify accessibility
- review visual quality
- fix issues

Do not start My Schedule until Employee Home is complete.

---

# 37. TESTING

Add or update meaningful tests for:

## AUTHENTICATION

- anonymous user cannot access Employee portal
- authenticated Employee can access their portal

## AUTHORIZATION

- Employee cannot access another Employee's data
- Employee cannot access Manager pages
- Employee cannot access Admin pages
- Manager/Admin behavior remains correct

## ATTENDANCE

- check-in works through existing service
- duplicate check-in is safely rejected
- check-out works
- invalid states are handled

## SCHEDULE

- Employee sees only their own schedule

## LEAVE

- Employee sees only their own requests
- Employee can submit valid request
- Employee cannot modify another Employee's request
- Manager can review authorized team requests

## PROFILE

- Employee can modify only permitted fields
- company-controlled fields cannot be modified

## EMPLOYEE CREATION

- Admin/Manager can create Employee according to authorization
- account creation follows existing security rules
- Employee receives correct role/access

Do not create hundreds of low-value tests.

Focus on:

- business logic
- authorization
- security
- data integrity
- critical user workflows

---

# 38. REVIEW PROCESS

Use a lightweight review process.

Do NOT spawn a large number of subagents.

Prefer:

Main Claude
     │
     ├── Implementation
     │
     └── One Reviewer

Use one Reviewer agent for the completed feature.

Only use another specialized agent if there is a genuine need.

Do NOT make several agents independently rewrite the same page.

Avoid unnecessary token consumption.

The Reviewer should inspect:

- security
- authorization
- business logic
- UX
- accessibility
- responsive behavior
- visual quality
- code quality
- regressions
- tests

---

# 39. REVIEW CHECKLIST

Before a feature is considered complete:

## ARCHITECTURE

- Existing architecture respected
- Routes remain thin
- Business logic remains in services
- No duplicate logic
- Existing components reused where appropriate

## SECURITY
- Authentication enforced
- Authorization enforced
- No IDOR
- No cross-Employee access
- Sensitive data protected
- Input validated
- CSRF preserved
- No client-side-only authorization

## BUSINESS LOGIC

- Existing services reused
- No invented policies
- Calculations correct
- Edge cases handled

## UX

- Primary action obvious
- Information hierarchy clear
- Loading states
- Empty states
- Error states
- No-results states
- Natural interaction flow

## VISUAL

- Professional
- Modern
- Consistent
- Strong typography
- Good spacing
- Appropriate iconography
- No excessive decoration
- Not generic CRUD
- Employee experience clearly differentiated from Admin/Manager
- Mobile experience intentionally designed

## ACCESSIBILITY

- Keyboard navigation works
- Focus states visible
- Contrast is sufficient
- Forms have labels
- Errors are understandable
- Status is not color-only
- Reduced motion supported

## PERFORMANCE

- No unnecessary queries
- No duplicate service calls
- No unnecessary dependencies
- No unnecessary JavaScript
- No duplicated calculations

## TESTING

- Relevant tests pass
- Existing tests remain green
- Authorization tests exist for sensitive functionality
- No regressions introduced

---

# 40. DO NOT OVERBUILD MVP 1

This is still MVP 1.

Do NOT implement:

- AI recommendations
- demand forecasting
- automatic scheduling
- workforce optimization
- anomaly detection
- AI assistant
- advanced predictive analytics

Those belong to later phases.

The purpose of this work is to establish an excellent foundation and a polished Employee experience.

---

# 41. MVP 1 SUCCESS CRITERIA

MVP 1 should provide a coherent workforce-management workflow:

ADMIN / MANAGER
       │
       ▼
Create Employee
       │
       ▼
Employee Account
       │
       ▼
Employee Login
       │
       ▼
Employee Home
       │
       ├── Check In
       ├── Check Out
       ├── Today's Shift
       ├── My Schedule
       ├── My Hours
       ├── Attendance
       ├── Leave
       └── Profile

The experience should feel like one coherent product rather than unrelated pages.

---

# 42. FINAL INSTRUCTION

Treat this as a real product, not a coding exercise.

Do not optimize for:

- number of files changed
- number of components created
- number of tests created
- amount of code generated
- number of subagents used

Optimize for:

Correctness
+
Security
+
Data Integrity
+
Usability
+
Visual Quality
+
Accessibility
+
Maintainability

Work carefully.

Inspect first.

Reuse existing architecture.

Implement one feature at a time.

After each feature:

1. Test it.
2. Review it.
3. Fix problems.
4. Verify authorization.
5. Verify responsive behavior.
6. Verify accessibility.
7. Verify visual quality.
8. Only then move to the next feature.

Do not move to the next Employee feature if the current feature is incomplete.

START WITH:

E1 — Employee Account + Employee Home

Do not modify unrelated pages.
