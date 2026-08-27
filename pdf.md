# PROJECT DOCUMENTATION — TECHNICAL SYSTEM BOOK

I want you to create a comprehensive technical documentation book for this entire Workforce Management Platform.

The purpose of this document is NOT marketing.

The purpose is to allow me, as the developer of this project, to:

- Understand the entire system deeply.
- Understand how every part of the application works.
- Understand the database and relationships.
- Understand every page and what it does.
- Understand authentication and authorization.
- Understand the business logic.
- Understand how data flows through the application.
- Understand the important security decisions.
- Understand the architecture well enough to explain the system to another developer or a company.
- Use the document as a long-term technical reference while continuing development.

The final result MUST be a professional PDF generated from LaTeX.

---

# 1. SOURCE OF TRUTH

The actual codebase is the ONLY source of truth.

Before writing the documentation, inspect the real project carefully.

You MUST inspect, where applicable:

- CLAUDE.md
- .claude/rules/
- .claude/agents/
- app/
- app/routes/
- app/services/
- app/models/
- app/auth/
- templates/
- static/
- tests/
- migrations/
- requirements.txt
- configuration files
- environment/configuration handling
- database models
- database migrations
- existing documentation
- SQL queries
- authorization logic
- business logic
- templates and UI structure

Do NOT document features that do not actually exist.

Do NOT invent routes.

Do NOT invent database relationships.

Do NOT invent security mechanisms.

Do NOT infer functionality merely because it would be desirable.

If something is planned but not implemented, explicitly label it:

PLANNED / NOT IMPLEMENTED

If something is partially implemented, explicitly label it:

PARTIALLY IMPLEMENTED

If something is unclear from the source code, label it:

NEEDS VERIFICATION

Never silently guess.

---

# 2. DOCUMENT PURPOSE

This document should function as a technical "book" for studying the project.

I should be able to use it to answer questions such as:

- What is this application?
- Why does each part exist?
- How does a request move through the application?
- How does authentication work?
- How does authorization work?
- How does an employee check in?
- How does an employee check out?
- How are working hours calculated?
- How are schedules represented?
- How does leave work?
- How is overtime calculated?
- How is labor cost calculated?
- How are managers restricted to their authorized data?
- How does the Admin Dashboard obtain its data?
- What tables exist?
- How are the tables related?
- Where is each business rule implemented?
- Where should I make a change if I add a feature?
- What tests protect each important behavior?
- What security decisions were made?
- What is implemented and what remains?

The documentation should therefore explain BOTH:

1. The product/domain.
2. The technical implementation.

---

# 3. DOCUMENT LANGUAGE

Write the documentation in clear professional English.

Use technical terminology accurately.

The document is intended for a developer who wants to understand the system deeply.

Do not write marketing language.

Explain concepts before using complicated terminology.

When useful, explain each concept using:

1. What it is.
2. Why the project uses it.
3. How this project implements it.
4. Where it exists in the code.
5. A concrete example.

---

# 4. OUTPUT FORMAT

Create a professional PDF using:

- LaTeX
- A clean technical-documentation layout
- Table of contents
- Numbered sections
- Numbered subsections
- Tables
- Code snippets
- Architecture diagrams
- Database diagrams
- Tree diagrams
- Flow diagrams
- Call-flow diagrams where useful

The document should look like a professional internal engineering document.

Do NOT simply dump source code into the PDF.

The goal is understanding.

Use concise code snippets only when they help explain important behavior.

---

# 5. DOCUMENT STRUCTURE

Create the PDF with the following structure.
Adjust the structure when the actual codebase requires it.

Do not force sections that do not apply.

---

# COVER PAGE

Include:

Workforce Management Platform

Technical System Documentation

MVP 1

Then include:

- Project purpose
- Technology stack
- Documentation version
- Generated date

Do not include fictional company information.

---

# TABLE OF CONTENTS

Generate a proper LaTeX table of contents.

---

# PART I — SYSTEM OVERVIEW

## 1. What Is This System?

Explain:

- What problem the system solves.
- Who uses it.
- What the system manages.
- What the major workflows are.
- What makes it a Workforce Management System.

Explain the relationship between:

- Workforce Management
- Attendance tracking
- Scheduling
- Leave management
- Labor cost tracking
- Reports
- Workforce administration

Explain how these concepts connect.

---

## 2. Product Scope

Create a table:

| Capability | Status | Description |
|------------|--------|-------------|

Include actual capabilities such as:

- Authentication
- Employees
- User accounts
- Departments
- Scheduling
- Check-in
- Check-out
- Attendance
- Working hours
- Leave
- Overtime
- Labor Cost
- Reports
- Audit Log
- Roles
- Permissions

Only include capabilities that actually exist.

Clearly separate:

- IMPLEMENTED
- PARTIALLY IMPLEMENTED
- PLANNED / NOT IMPLEMENTED

---

# PART II — TECHNOLOGY STACK

## 3. Technology Stack

Explain every major technology used by the actual project.

For example, where applicable:

- Python
- Flask
- PostgreSQL
- SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-WTF
- Argon2
- Gunicorn
- HTML
- CSS
- JavaScript

For every major technology explain:

### What is it?

### Why is it used?

### Where is it used in this project?

### What responsibility does it have?

Do not document technologies that are not actually used.

---

## 4. High-Level Architecture

Explain the architecture.

If the application is a modular monolith, explain what that means.

Create a real architecture diagram based on the source code.

For example, conceptually:

Browser
    |
    v
Flask Application
    |
    +-------------------+
    |                   |
    v                   v
Routes             Authentication
    |
    v
Services
    |
    v
SQLAlchemy
    |
    v
PostgreSQL

Do NOT blindly use this example.

Generate the actual architecture.

Use LaTeX diagrams such as TikZ where appropriate.

Explain:

- Why routes should remain thin.
- Why business logic belongs in services.
- Why models represent persistence.
- How authorization is enforced.
- How data travels through the system.
- How templates are rendered.
- How the database is accessed.

---

# PART III — PROJECT STRUCTURE

## 5. Complete Project Tree

Generate a real tree representation of the repository.

Example:

project/
├── app/
│   ├── routes/
│   ├── services/
│   ├── models/
│   ├── auth/
│   └── ...
├── templates/
├── static/
├── tests/
├── migrations/
└── ...

IMPORTANT:

Generate this from the actual repository.

Do not invent files.

For every important directory explain:

- Purpose
- Responsibility
- Important files

For important files explain:

- What they contain.
- Why they exist.
- What depends on them.

Do not document every trivial file if doing so makes the document unreadable.

---

# PART IV — APPLICATION ROUTING

## 6. Route / Blueprint Architecture

Create a complete map of the Flask routes.

For every blueprint document:

- Blueprint name
- Purpose
- Routes
- HTTP methods
- Authentication requirement
- Role requirement
- Service functions called
- Template rendered
- Important behavior

Create a table similar to:

| Blueprint | Route | Method | Auth | Role | Service | Template |
|-----------|-------|--------|------|------|---------|----------|

Only use real information from the source.

---

## 7. Request Lifecycle

Explain what happens when a user opens a page.

Create a real flow diagram.

Conceptually:
Browser
   |
   v
HTTP Request
   |
   v
Flask Route
   |
   v
Authentication
   |
   v
Authorization
   |
   v
AccessScope
   |
   v
Service Layer
   |
   v
SQLAlchemy
   |
   v
PostgreSQL
   |
   v
Service Result
   |
   v
Jinja Template
   |
   v
HTML Response

Adapt this to the actual implementation.

Explain every step.

---

# PART V — AUTHENTICATION AND AUTHORIZATION

## 8. Authentication

Explain:

- Login
- Logout
- Sessions
- Password hashing
- Password verification
- Account lockout if implemented
- Authentication state
- Unauthorized requests
- Session behavior

Explain where each mechanism exists in the code.

---

## 9. Authorization

This section is extremely important.

Explain:

- Roles
- Permissions
- role_required
- AccessScope
- Organization scoping
- Manager department scoping
- Admin privileges
- Manager privileges
- Employee privileges

Explain the defense-in-depth model if implemented.

Create a diagram such as:

Request
   |
   v
Route Authorization
   |
   v
Service Authorization
   |
   v
Database Query Scoping
   |
   v
Authorized Data

Explain why authorization should not rely only on hiding UI elements.

---

## 10. Role Matrix

Create a complete role matrix:

| Feature | ADMIN | MANAGER | EMPLOYEE |
|---------|-------|---------|----------|

Populate it using the actual authorization behavior.

Do not guess.

If more roles exist, include them.

---

# PART VI — DATABASE

## 11. Database Architecture

Explain:

- PostgreSQL
- SQLAlchemy
- Models
- Relationships
- Foreign keys
- Constraints
- Indexes
- Transactions where applicable
- Migrations

Explain how application objects map to database records.

---

## 12. Database Table Inventory

Create a complete table of all actual database tables.

For each table include:

| Table | Purpose | Primary Key | Important Columns |
|-------|---------|-------------|-------------------|

Explain important columns.

Do not include fictional tables.

---

## 13. Entity Relationship Diagram

Create a REAL ER diagram using the actual models and database structure.

Show:

- Tables
- Primary keys
- Foreign keys
- One-to-one relationships
- One-to-many relationships
- Many-to-many relationships where applicable

Use LaTeX/TikZ or another LaTeX-compatible diagram approach.

Do NOT create a fictional ERD.

The diagram must reflect the actual schema.

---

## 14. Database Relationship Explanation

After the ER diagram, explain every important relationship.

For example, conceptually:

Organization
    |
    +---- Departments
              |
              +---- Employees
                        |
                        +---- Attendance
                        |
                        +---- Schedules
                        |
                        +---- Leave
                        |
                        +---- User

Adapt this to the actual database.

Explain why the relationships exist.

---

## 15. Constraints and Data Integrity

Document important:

- UNIQUE constraints
- CHECK constraints
- Foreign keys
- NOT NULL constraints
- Date constraints
- Overlap constraints
- Indexes
- Cascade behavior
- Other database-level integrity mechanisms

Explain why each important constraint matters.

---

# PART VII — BUSINESS DOMAIN

## 16. Employee Domain

Explain:

- Employee lifecycle
- Employee creation
- Employee editing
- Employee/departments relationship
- Employee/user relationship
- Employee configuration
- Relevant business rules

---

## 17. User Account Domain

Explain how an employee account relates to the employee record.

Document:

- Account creation
- Authentication
- Role assignment
- Employee association
- Account status if implemented
- Permissions
- What the employee can access

Create a relationship diagram where useful:

User
 |
 +---- Role
 |
 +---- Employee
          |
          +---- Schedule
          +---- Attendance
          +---- Leave
          +---- Worked Hours

Adapt to the actual schema.

---

## 18. Scheduling Domain

Explain:
- Shifts
- Scheduling
- Published shifts
- Department relationships
- Employee assignments
- Overlap prevention
- Effective dates
- Validation

Create a scheduling flow diagram where useful.

---

## 19. Attendance Domain

Explain the ACTUAL implementation.

Document:

- Check-in
- Check-out
- Attendance records
- Working duration
- Break handling
- Attendance correction
- Needs-review behavior
- Authorization
- Validation
- Edge cases

IMPORTANT:

Do not describe a future attendance state machine unless it actually exists.

If a richer attendance state machine is planned but not implemented, explicitly explain the difference.

---

## 20. Leave Domain

Explain:

- Leave requests
- Request states
- Approval
- Rejection
- Cancellation
- Authorization
- Database state transitions

Create a state diagram if appropriate.

Only use actual states.

---

## 21. Overtime Domain

Explain:

- Overtime calculation
- Effective dates
- Policies
- Rules
- Reports
- Authorization

Explain the actual calculation logic.

Do not simplify it incorrectly.

---

## 22. Labor Cost Domain

Explain:

- What Labor Cost means in this application.
- How it is calculated.
- What data it depends on.
- How rounding works.
- How overtime affects it.
- How department aggregation works.
- What information admins can see.
- What information managers cannot see.
- How monetary values are represented.
- Why Decimal is used instead of floating-point arithmetic if implemented.

Use actual implementation details.

---

## 23. Reports

Document every existing report.

For each:

- Purpose
- Inputs
- Filters
- Data source
- Calculations
- Authorization
- Output
- Relevant source files

---

## 24. Audit Log

Explain:

- What events are logged.
- How entries are created.
- Whether entries are append-only.
- Who can view them.
- Why audit logs matter.
- How authorization protects them.

---

# PART VIII — EVERY APPLICATION PAGE

## 25. Page-by-Page Documentation

This section is extremely important.

Create one subsection for EVERY real page in the application.

For each page document:

### Page Name

### Purpose

What problem does the page solve?

### URL / Route

### Who can access it?

### Main UI Elements

### Data displayed

### User actions

### Backend route

### Service functions

### Database data involved

### Authorization

### Validation

### Important edge cases

### Error states

### Related pages

### Relevant source files

Then include a simplified visual wireframe representing the actual page.

Example:

+------------------------------------------------------+
| Sidebar | Page Title                    User Menu     |
+------------------------------------------------------+
|        | Filters                                      |
|        |                                               |
|        | Metrics                                       |
|        |                                               |
|        | Data table                                    |
|        |                                               |
+------------------------------------------------------+

The wireframe must represent the actual page.

Do not invent UI elements.

---

# PART IX — ADMIN DASHBOARD

## 26. Admin Dashboard Deep Dive

Document the Admin Dashboard separately.

Explain:

- Purpose
- Metrics
- Workforce status
- Attendance
- Departments
- Coverage
- Labor cost
- Recent activity
- Filters
- Admin-only information
- Manager-safe information

Create a real data-flow diagram.

Conceptually:

Database
   |
   +--> Employee data
   |
   +--> Attendance
   |
   +--> Schedule
   |
   +--> Leave
   |
   +--> Labor Cost
   |
   v
Dashboard Service
   |
   v
Dashboard Route
   |
   v
Jinja Template

Use the actual implementation.

---

# PART X — FRONTEND / DESIGN SYSTEM

## 27. Frontend Architecture

Explain:

- Templates
- Jinja
- CSS architecture
- JavaScript
- Components
- Design tokens
- Responsive system
- Accessibility

---

## 28. Design System

Document:
- Typography
- Fonts
- Colors
- Semantic colors
- Spacing
- Border radius
- Buttons
- Forms
- Tables
- Cards
- Status badges
- Metric cells
- Navigation
- Focus states
- Reduced motion
- Icons if implemented

Explain the reasoning behind the design system where documented in the project.

---

# PART XI — SECURITY

## 29. Security Architecture

Document actual security mechanisms.

Include:

- Authentication
- Password hashing
- Session security
- Authorization
- Access scopes
- CSRF protection
- Input validation
- SQL injection protection
- XSS protection
- Secure cookies
- Security headers
- Cache control
- Production configuration
- Error handling
- Sensitive information exposure

Do NOT claim something is secure merely because Flask provides a feature.

Verify the implementation.

---

## 30. Security Threat Model

Create a practical threat model.

For example:

External User
      |
      +-------------------+
      |                   |
      v                   v
Authentication     Input Validation
      |                   |
      +---------+---------+
                |
                v
          Authorization
                |
                v
          Service Layer
                |
                v
             Database

Explain realistic threats relevant to this application.

Do not create an enormous theoretical security report.

Focus on practical risks.

---

# PART XII — TESTING

## 31. Testing Architecture

Explain:

- Test structure
- Unit tests
- Integration tests
- Route tests
- Authorization tests
- Database tests
- Business logic tests

Create a tree of the test suite.

---

## 32. Important Test Cases

Identify the most important tests.

Especially:

- Authentication
- Authorization
- Role separation
- Organization scoping
- Manager department scoping
- Attendance
- Scheduling
- Leave
- Overtime
- Labor cost
- Audit logging

Explain what each test protects against.

---

# PART XIII — DATA FLOWS

## 33. Important System Flows

Create diagrams for the most important workflows.

At minimum:

### Login Flow

User
 ↓
Login Form
 ↓
Authentication
 ↓
Password Verification
 ↓
Session
 ↓
Dashboard

### Check-In Flow

Employee
 ↓
Check In
 ↓
Authorization
 ↓
Attendance Service
 ↓
Database
 ↓
Active Work Session

### Check-Out Flow

Employee
 ↓
Check Out
 ↓
Attendance Service
 ↓
Duration Calculation
 ↓
Database

### Leave Request Flow

Employee
 ↓
Request Leave
 ↓
Validation
 ↓
Database
 ↓
Manager/Admin
 ↓
Approve / Reject

Adapt all flows to the actual implementation.

---

# PART XIV — BUSINESS RULES

## 34. Business Rules Catalog

Create a clear list of important business rules.

Use this format:

BR-001

Name:
Description:
Where implemented:
Why it exists:
Tests protecting it:

Include actual rules discovered in the source.

Do not invent business rules.

---

# PART XV — ERROR AND EDGE CASES

## 35. Error Handling

Explain important failure cases:

- Invalid login
- Unauthorized access
- Forbidden access
- Missing employee
- Invalid schedule
- Overlapping shift
- Invalid leave request
- Invalid attendance operation
- Missing configuration
- Database errors
- Validation failures

Explain how the application responds.

---

# PART XVI — DEPLOYMENT

## 36. Deployment Architecture

Document how the application is intended to run.

Include actual components such as:

- Flask
- Gunicorn
- PostgreSQL
- Environment variables
- Production configuration
- Static files
- Migrations

Create a deployment diagram based on the actual project.

Do not invent infrastructure that does not exist.

---

## 37. Configuration

Document important configuration variables.

Do NOT print real secrets.

Use:

DATABASE_URL=<REDACTED>
SECRET_KEY=<REDACTED>

Never include:

- Passwords
- API keys
- Tokens
- Secret keys
- Database credentials
- Session secrets
- Private credentials

---

# PART XVII — MAINTENANCE

## 38. How To Add a New Feature

Explain the correct development workflow for this architecture.

For example:
Requirement
    ↓
Business Rule
    ↓
Database / Model
    ↓
Service
    ↓
Route
    ↓
Template
    ↓
Tests
    ↓
Security Review

Explain when each layer should be modified.

Explain what should NOT be done.

---

## 39. How To Add a New Page

Explain:

1. Route
2. Authorization
3. Service
4. Template
5. CSS/components
6. Tests

Explain how to keep the architecture clean.

---

## 40. How To Modify Existing Business Logic

Explain:

- Where logic should live.
- What tests should be updated.
- What authorization must be reconsidered.
- What database integrity concerns exist.
- What regression risks exist.

---

# PART XVIII — CURRENT LIMITATIONS

## 41. Known Limitations

Create a table:

| Area | Current State | Limitation | Impact | Future Direction |
|------|---------------|------------|--------|------------------|

Only include limitations verified from the actual codebase.

Separate:

- Technical limitations
- Product limitations
- UX limitations
- Security limitations
- Planned features

---

# PART XIX — FUTURE DEVELOPMENT

## 42. Recommended Roadmap

Create a technically sensible roadmap based on the current implementation.

Separate:

### MVP 1

### MVP 2

### Future

Do not turn every possible idea into a requirement.

Prioritize:

1. Security
2. Data integrity
3. Core workforce workflows
4. User experience
5. Reporting
6. Scalability
7. Advanced functionality

Clearly distinguish existing implementation from recommendations.

---

# PART XX — DEVELOPER QUICK REFERENCE

## 43. One-Page System Map

Create a concise final reference page containing the complete system at a glance.

Conceptually:

Users
 ↓
Authentication
 ↓
Roles
 ↓
AccessScope
 ↓
Routes
 ↓
Services
 ↓
Models
 ↓
PostgreSQL

Then show the main domain relationships.

Adapt everything to the actual project.

---

## 44. Important Files Cheat Sheet

Create a table:

| File | Purpose | When I need to edit it |
|------|---------|------------------------|

Include only the most important files.

---

## 45. Glossary

Explain important terms such as:

- Blueprint
- Route
- Service
- Model
- ORM
- AccessScope
- Role
- Authentication
- Authorization
- Attendance
- Shift
- Overtime
- Labor Cost
- Audit Log
- Migration
- Transaction
- Constraint
- Index

Make the glossary specific to this project.

---

## 46. FINAL SYSTEM SUMMARY

Finish the document with a clear explanation of:

1. What the system is.
2. How it is structured.
3. How data flows.
4. How users interact with it.
5. How authentication works.
6. How authorization works.
7. How the database is structured.
8. What the most important business rules are.
9. What is currently implemented.
10. What remains to be built.
11. What a new developer needs to understand first.

---

# 6. DIAGRAM REQUIREMENTS

The documentation MUST contain useful diagrams.

At minimum include:

1. Project directory tree
2. High-level architecture diagram
3. Request lifecycle
4. Authentication flow
5. Authorization flow
6. Database ER diagram
7. Role/permission matrix
8. Check-in flow
9. Check-out flow
10. Leave workflow/state diagram
11. Admin Dashboard data flow
12. Deployment architecture
13. Development architecture
14. Final system map

Prefer:

- TikZ
- PGF/TikZ
- forest
- tabularx
- longtable
- listings
- hyperref

Use diagrams where they improve understanding.

Do not fill pages with decorative diagrams.

Every diagram should teach me something about the actual system.

---

# 7. CODE REFERENCES

When referring to implementation details, include source references such as:

app/services/attendance.py
app/routes/dashboard.py
app/auth/decorators.py
templates/dashboard/admin.html

For important functions, include:

Function:
Location:
Purpose:
Inputs:
Output:
Authorization:
Important edge cases:
Tests:

Do not include huge source-code blocks.

Include only concise snippets when they genuinely help understanding.

---

# 8. DATABASE VERIFICATION

The ERD and database documentation are especially important.

Extract the actual schema from:

- SQLAlchemy models
- migrations
- foreign keys
- constraints
- indexes
Cross-check models against migrations.

If there is a discrepancy, document it explicitly.

Do NOT assume that the SQLAlchemy model is always identical to the deployed database.

Explain the relationship:

Model
  ↓
Migration
  ↓
PostgreSQL Table

where relevant.

---

# 9. PAGE DOCUMENTATION REQUIREMENT

I specifically want to understand EVERY page.

Do not only document major pages.

Find all actual user-facing pages/routes and document them.

For each page answer:

- Why does this page exist?
- Who uses it?
- What can the user see?
- What can the user do?
- What data does it load?
- Where does that data come from?
- Which route handles it?
- Which service handles the business logic?
- Which database tables are involved?
- What authorization is applied?
- What happens if the user is unauthorized?
- What validation exists?
- What happens on success?
- What happens on failure?
- Which other pages does it connect to?

This section should allow me to study the application page-by-page without opening the source code first.

---

# 10. BUSINESS LOGIC REQUIREMENT

Do not merely say:

"The service calculates overtime."

Explain HOW it calculates overtime.

For important calculations, document:

- Inputs
- Preconditions
- Formula/algorithm
- Rounding
- Edge cases
- Database dependencies
- Authorization
- Output
- Tests

Do the same for:

- Working hours
- Attendance duration
- Overtime
- Labor cost
- Leave validation
- Schedule validation
- Any other important calculation.

If a mathematical formula is useful, use proper LaTeX mathematical notation.

For example:

\[
\text{Labor Cost} =
\sum_{i=1}^{n}
\left(
\text{Worked Hours}_i
\times
\text{Hourly Rate}_i
\right)
\]

BUT only include a formula if it accurately represents the actual implementation.

Never replace actual implementation details with a simplified formula that changes the meaning.

---

# 11. SECURITY REQUIREMENT

Never expose secrets in the documentation.

NEVER include:

- Passwords
- Secret keys
- API keys
- Database passwords
- Session secrets
- Tokens
- Credentials
- Private URLs containing credentials

Replace them with:

<REDACTED>

Also explain security decisions rather than exposing sensitive configuration.

---

# 12. ACCURACY REQUIREMENT

Before generating the final PDF, perform a documentation consistency check.

Verify that:

- Every documented route exists.
- Every documented model exists.
- Every documented service exists.
- Every documented table exists.
- Every documented relationship exists.
- Every documented role exists.
- Every documented permission matches the implementation.
- Every documented workflow matches the implementation.
- Every documented calculation matches the actual code.
- No secret appears in the document.
- No fictional feature is presented as implemented.
- No planned feature is presented as completed.

If something cannot be verified, mark it:

NEEDS VERIFICATION

If something is planned:

PLANNED / NOT IMPLEMENTED

If something is incomplete:

PARTIALLY IMPLEMENTED

---

# 13. LATEX QUALITY

The LaTeX should be clean and maintainable.

Use a sensible structure such as:

docs/
└── system-documentation/
    ├── main.tex
    ├── chapters/
    ├── diagrams/
    ├── figures/
    └── output/

Adapt this if the project already has an established documentation structure.

Do not overwrite existing documentation without checking it first.

Use appropriate packages such as:

- geometry
- xcolor
- hyperref
- graphicx
- booktabs
- longtable
- tabularx
- listings
- tikz
- forest
- amsmath
- amssymb
- enumitem
- fancyhdr

Only use packages that are actually necessary.

Keep the document visually clean and professional.

---

# 14. PDF DESIGN

The PDF should feel like a professional internal engineering handbook.

Use:

- Clear hierarchy
- Consistent typography
- Good margins
- Page numbers
- Headers/footers
- Table of contents
- Figure captions
- Table captions
- Cross references
- Consistent code formatting
- Consistent diagram styling
- Proper spacing
- Readable tables

Avoid:
- Excessive decoration
- Random colors
- Huge walls of text
- Huge source-code dumps
- Unnecessary screenshots
- Repetition
- Decorative diagrams with no information

Prioritize readability and study value.

---

# 15. BUILD THE PDF

Create the LaTeX source.

Compile it into:

Workforce-Management-System-Documentation.pdf

If LaTeX compilation fails:

1. Diagnose the actual error.
2. Fix it.
3. Recompile.
4. Verify the resulting PDF.

Do not stop at creating main.tex.

I need the actual compiled PDF.

---

# 16. PDF VERIFICATION

After compiling the PDF, verify:

- The PDF exists.
- It opens correctly.
- Table of contents is present.
- Page numbers work.
- Diagrams render correctly.
- Tables are readable.
- Code listings render correctly.
- Mathematical notation renders correctly.
- No pages are accidentally blank.
- No major content is cut off.
- No secrets are present.
- No fictional functionality is documented.

If possible, inspect the rendered PDF pages rather than assuming that successful compilation means the PDF looks correct.

---

# 17. TOKEN / CONTEXT EFFICIENCY

This is a large documentation task.

Be efficient.

Do NOT repeatedly read the entire repository unnecessarily.

Work systematically:

1. Inspect and map the repository.
2. Identify architecture.
3. Identify routes.
4. Identify services.
5. Identify models/database.
6. Identify templates/pages.
7. Identify business logic.
8. Identify security.
9. Identify tests.
10. Generate documentation.
11. Verify documentation.
12. Compile PDF.
13. Inspect PDF.

Do NOT use large numbers of subagents.

Use the main context for the majority of the work.

If subagents are used, use at most a very small number and only for genuinely independent analysis.

Do not have multiple agents repeatedly analyze the same files.

Do not run the full test suite unless genuinely needed for documentation verification.

This is a DOCUMENTATION task, not a feature-development task.

Do NOT modify product functionality.

---

# 18. IMPORTANT: DO NOT CHANGE THE APPLICATION

During this task:

DO NOT:

- Add product features.
- Rewrite application architecture.
- Refactor business logic.
- Change database schema.
- Change authentication.
- Change authorization.
- Redesign application pages.
- Change production behavior.

Only create the documentation and any files necessary to compile the documentation.

If you discover a bug, inconsistency, or architectural concern:

DOCUMENT IT.

Do not automatically fix it.

---

# 19. FINAL OUTPUT

When everything is complete, give me:

1. The exact path of the generated PDF.
2. The exact path of the main LaTeX source.
3. The documentation directory structure.
4. A concise summary of what the documentation contains.
5. Any important inconsistencies discovered.
6. Any sections marked NEEDS VERIFICATION.
7. Any features marked PLANNED / NOT IMPLEMENTED.
8. Any important technical/security issues discovered during documentation.

Do not start implementing product features.

This task is ONLY to create the technical documentation and system study book.

The final document should allow me to study the entire application, understand its architecture and business logic, explain it professionally, and continue developing it safely.

