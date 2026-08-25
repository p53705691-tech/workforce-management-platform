# WORKFORCE MANAGEMENT PLATFORM
# UI / UX DESIGN DIRECTION & IMPLEMENTATION BRIEF

You are designing and implementing the frontend experience for a
production-oriented Workforce Management Platform.

The project is NOT a copy of the provided reference component.

The provided component is a VISUAL AND DESIGN REFERENCE ONLY.

Your task is to extract its visual language, interaction philosophy,
spacing, typography, component quality, minimalism, and overall aesthetic,
then create a coherent design system and application UI specifically
for this Workforce Management Platform.

============================================================
1. IMPORTANT: REFERENCE ≠ PRODUCT
============================================================

The reference code provided below is NOT the application's architecture.

Do NOT blindly copy:

- its page structure
- its content
- its business logic
- its feature names
- its data
- its React architecture
- its dependencies
- its animations
- its components

Use it only to understand the desired visual direction.

The resulting application must feel INSPIRED BY the reference,
not identical to it.

The final product should look like the same design family,
but clearly belong to a Workforce Management SaaS product.

The design should be:

- Modern
- Minimal
- Professional
- Clean
- Calm
- Functional
- Consistent
- Premium without being flashy
- Data-oriented
- Easy to understand
- Suitable for long-term daily use

Avoid making the application look like a marketing landing page.

This is a WORK APPLICATION.

Users may spend hours inside it every day.

Usability and information hierarchy are more important than visual effects.

============================================================
2. EXISTING TECHNOLOGY STACK
============================================================

The current application stack is:

Backend:
- Python
- Flask
- SQLAlchemy
- PostgreSQL

Frontend:
- HTML
- Jinja templates
- CSS
- Vanilla JavaScript

Testing:
- pytest

IMPORTANT:

Do NOT migrate the project to React.

Do NOT introduce Next.js.

Do NOT introduce TypeScript.

Do NOT introduce Tailwind CSS unless the project has explicitly been
changed to use it.

Do NOT replace Flask/Jinja with another frontend architecture.

The provided React/shadcn component is a DESIGN REFERENCE,
not an instruction to change the technology stack.

Recreate the relevant visual ideas using the existing project stack.

============================================================
3. DESIGN PHILOSOPHY
============================================================

The application should follow a modern minimal SaaS design language.

Think:

- clean layouts
- strong typography
- subtle borders
- restrained shadows
- generous whitespace
- clear hierarchy
- subtle interaction feedback
- consistent spacing
- compact but readable data presentation

Avoid:

- excessive gradients
- excessive glassmorphism
- excessive rounded cards
- giant decorative elements
- excessive animations
- visual noise
- random colors
- unnecessary icons
- oversized dashboards
- marketing-style hero sections inside the application
- decorative UI that does not communicate useful information

The interface should feel intentionally designed rather than
assembled from unrelated components.

============================================================
4. VISUAL LANGUAGE FROM THE REFERENCE
============================================================

Extract and adapt the following qualities from the reference:

- subtle grid/dashed-line patterns where appropriate
- restrained visual decoration
- strong typography
- clean card layouts
- minimal borders
- subtle muted colors
- clear spacing
- responsive layouts
- small meaningful icons
- subtle motion
- elegant empty states
- visual hierarchy through typography rather than excessive color

Do NOT use the reference's decorative patterns everywhere.

Decorative elements should be used sparingly.

The dashboard and operational screens must remain information-first.

============================================================
5. DESIGN SYSTEM
============================================================

Before implementing many pages, establish a coherent design system.

Create reusable styles/components for:

- Typography
- Headings
- Body text
- Muted text
- Page titles
- Section titles
- Buttons
- Inputs
- Selects
- Search fields
- Checkboxes
- Radio buttons
- Tables
- Cards
- Badges
- Status indicators
- Alerts
- Toasts
- Modals
- Dropdowns
- Tabs
- Breadcrumbs
- Pagination
- Empty states
- Loading states
- Error states
- Skeleton states
- Sidebar
- Topbar
- Navigation
- Forms
- Confirmation dialogs

Use CSS variables/tokens for:

- colors
- spacing
- border radius
- shadows
- typography
- transitions

Avoid hardcoding the same visual values repeatedly.

The entire application should visually behave as ONE product.

============================================================
6. APPLICATION SHELL
============================================================

Create a consistent authenticated application shell.

Conceptually:

------------------------------------------------------
| Sidebar              | Topbar                      |
|                      |                             |
| Dashboard            |                             |
| Employees            |        Main Content         |
| Departments          |                             |
| Schedule             |                             |
| Attendance           |                             |
| Working Hours        |                             |
| Overtime             |                             |
| Leave                |                             |
| Reports              |                             |
|                      |                             |
| Settings              |                             |
------------------------------------------------------

The exact visual implementation should be inspired by the reference,
but adapted to the application's information architecture.

The shell must be reusable.

Do NOT duplicate sidebar/topbar markup across pages.

Use Jinja template inheritance and reusable macros/components where
appropriate.

The application shell should support:

- active navigation state
- responsive behavior
- mobile navigation
- user menu
- notifications where applicable
- breadcrumbs where useful
- page title
- contextual actions

============================================================
7. INFORMATION ARCHITECTURE
============================================================

The application must have separate pages for separate concepts.

Do NOT build one giant dashboard containing everything.

Create dedicated experiences for:

1. Dashboard
2. Employees
3. Employee Details
4. Departments
5. Schedule
6. Attendance
7. Working Hours
8. Overtime
9. Leave
10. Reports
11. Profile
12. Settings

Each page must have a clear purpose.

============================================================
8. DASHBOARD
============================================================

The Dashboard is an operational overview.

It should NOT attempt to contain every feature.

Possible sections:

- Total Employees
- Present Today
- Absent Today
- Late Arrivals
- Upcoming Shifts
- Pending Leave Requests
- Overtime Summary
- Working Hours Summary
- Recent Activity

Use a hierarchy such as:

Page Header
    ↓
Key Metrics
    ↓
Operational Overview
    ↓
Upcoming / Pending Items
    ↓
Recent Activity

Do not create fake metrics.

Only display information that exists in the backend/database.

If real data is not available yet, use clearly marked development
placeholders rather than pretending the data is real.

============================================================
9. EMPLOYEES PAGE
============================================================

The Employees page should be primarily a data-management experience.

Include:

- page title
- employee count
- search
- filters
- department filter
- status filter
- add employee action
- employee table
- pagination

Each employee row may show:
- name
- employee identifier
- department
- position
- status
- current shift
- actions

Use subtle status badges.

Avoid turning every row into a large card.

For desktop, prioritize table efficiency.

For mobile, provide an intentional responsive representation.

============================================================
10. EMPLOYEE DETAILS
============================================================

The employee details page should provide a focused view of one employee.

Organize information into meaningful sections:

- Profile
- Employment Information
- Department
- Current Schedule
- Attendance Summary
- Working Hours
- Overtime
- Leave

Use tabs or sections where appropriate.

Do not overload the page.

The employee details page should be useful to managers.

============================================================
11. DEPARTMENTS
============================================================

Provide:

- department list
- employee count
- manager
- status
- department details

Allow managers/admins to understand organizational structure quickly.

Do not create unnecessary visual complexity.

============================================================
12. SCHEDULE PAGE
============================================================

Schedule is one of the most important parts of the product.

The UI should make planned work visually understandable.

Possible views:

- Day
- Week
- Month

The initial MVP may prioritize:

WEEK VIEW

Show:

- employee
- date
- shift start
- shift end
- status

Use visual distinction between:

Scheduled
Working
Completed
Cancelled
Leave

Do not confuse scheduled work with actual attendance.

These are different domain concepts.

============================================================
13. ATTENDANCE PAGE
============================================================

Attendance represents ACTUAL work behavior.

It must remain visually distinct from Schedule.

Provide:

- today's attendance
- employee
- clock-in
- clock-out
- worked hours
- status
- late indicator
- missing clock-out indicator

Possible states:

Present
Late
Absent
Incomplete
On Leave

Use clear status indicators.

Do not rely only on color.

============================================================
14. WORKING HOURS PAGE
============================================================

Working Hours should answer:

"How much did the employee actually work?"

Provide:

- employee
- date
- scheduled hours
- actual hours
- difference
- overtime

The UI must visually distinguish:

Scheduled Hours

from

Actual Worked Hours

This distinction is critical to the domain.

============================================================
15. OVERTIME PAGE
============================================================

Provide a focused view of overtime.

Possible information:

- employee
- date
- normal hours
- worked hours
- overtime hours
- approval status

Do not invent labor-law calculations.

The UI should reflect backend-defined business rules.

============================================================
16. LEAVE PAGE
============================================================

Separate:

Employee experience:

- My Leave
- Leave balance if supported
- Submit request
- Request history

Manager experience:

- Pending Requests
- Approve
- Reject
- View request details

Use clear states:

Pending
Approved
Rejected
Cancelled

The design should make approval workflows obvious.

============================================================
17. REPORTS
============================================================

Reports should prioritize clarity over visual decoration.

MVP reports may include:

- Attendance
- Working Hours
- Overtime
- Leave

Use:

- filters
- date range
- department
- employee
- export action where supported

Charts should only be used when they make information easier to understand.

Do NOT add charts simply because dashboards are expected to have charts.

============================================================
18. SETTINGS
============================================================
Settings should be separate from operational workflows.

Potential sections:

- Account
- Organization
- Users
- Roles
- Preferences

Do not expose administrative controls to unauthorized users.

============================================================
19. RESPONSIVE DESIGN
============================================================

Design intentionally for:

- Desktop
- Laptop
- Tablet
- Mobile

Do not simply shrink desktop layouts.

For example:

Desktop:
Table

Mobile:
Stacked employee information / responsive row layout

Desktop:
Persistent sidebar

Mobile:
Collapsible navigation

Desktop:
Multi-column dashboard

Mobile:
Single-column hierarchy

Responsive behavior should be designed per component.

============================================================
20. ACCESSIBILITY
============================================================

Use semantic HTML.

Ensure:

- proper labels
- keyboard navigation
- visible focus states
- accessible forms
- meaningful buttons
- accessible error messages
- sufficient contrast
- non-color-only status communication

Do not sacrifice accessibility for visual similarity.

============================================================
21. MOTION
============================================================

Motion should be subtle.

Use animation only when it improves:

- feedback
- transitions
- hierarchy
- perceived responsiveness

Avoid:

- constant motion
- distracting animations
- excessive blur effects
- animations on every element

Respect:

prefers-reduced-motion

If animation is not useful, do not add it.

============================================================
22. ICONOGRAPHY
============================================================

Use a consistent icon set.

If the project already has an icon library, reuse it.

If adding icons is necessary, prefer a mature consistent icon library.

Do not use random SVG styles from different sources.

Icons should communicate meaning.

Do not use icons purely as decoration everywhere.

============================================================
23. DATA VISUALIZATION
============================================================

Use charts sparingly.

Charts should answer questions such as:

- Are working hours increasing?
- How much overtime occurred?
- What is the attendance trend?
- How much leave is pending?

Avoid decorative charts.

Use tables when precise values matter.

Use charts when patterns matter.

============================================================
24. FRONTEND ARCHITECTURE
============================================================

Use reusable Jinja templates.

Recommended conceptual structure:

templates/
├── base.html
├── components/
│   ├── navigation.html
│   ├── sidebar.html
│   ├── topbar.html
│   ├── button.html
│   ├── badge.html
│   ├── table.html
│   ├── modal.html
│   └── ...
│
├── dashboard/
│   └── index.html
│
├── employees/
│   ├── index.html
│   └── detail.html
│
├── departments/
│   └── index.html
│
├── schedule/
│   └── index.html
│
├── attendance/
│   └── index.html
│
├── working_hours/
│   └── index.html
│
├── overtime/
│   └── index.html
│
├── leave/
│   └── index.html
│
├── reports/
│   └── index.html
│
├── profile/
│   └── index.html
│
└── settings/
    └── index.html

static/
├── css/
│   ├── tokens.css
│   ├── base.css
│   ├── layout.css
│   ├── components.css
│   └── pages/
│
└── js/
    ├── app.js
    ├── components/
    └── pages/
