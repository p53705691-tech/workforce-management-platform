# Workforce Management Platform

## Project Overview

This project is a production-oriented Workforce Management Platform.

The platform helps organizations manage:

- Employees
- Departments
- Work schedules
- Attendance
- Working hours
- Overtime
- Leave requests
- Labor costs
- Reports
- Management dashboards

The long-term goal is to evolve the platform into an intelligent Workforce Management system with:

- Workforce demand forecasting
- AI-assisted scheduling
- Schedule optimization
- Advanced analytics

The current priority is a reliable, secure, maintainable MVP.

Do not attempt to clone Quinyx feature-for-feature.

Build a focused product with a clean architecture that can evolve over time.

---

## Product Philosophy

The system should answer practical business questions such as:

- Who is working today?
- Who is scheduled to work?
- Who actually worked?
- How many hours did each employee work?
- Who worked overtime?
- Who is absent?
- Who is on leave?
- How much is labor costing the company?
- Do we have enough employees scheduled?
- How are working hours changing over time?

The application should prioritize operational usefulness over unnecessary complexity.

---

# Technology Stack

Use the existing stack unless there is a strong technical reason to change it.

### Backend

- Python
- Flask
- SQLAlchemy
- Flask-Migrate / Alembic

### Database

- PostgreSQL

### Frontend

- HTML
- Jinja templates
- CSS
- Vanilla JavaScript

Use the existing frontend approach.

Do not introduce React, Vue, Angular, or another frontend framework unless explicitly requested or clearly justified.

### Testing

- pytest

### Production

- Gunicorn
- Docker
- Nginx when appropriate

---

# Architecture

Use a modular monolith.

Do not introduce microservices unless explicitly requested.

Prefer simple and understandable architecture over unnecessary abstraction.

The preferred flow is:

```text
HTTP Request
    ↓
Route / Controller
    ↓
Service / Business Logic
    ↓
Database Access
    ↓
SQLAlchemy / PostgreSQL
```

---

# Source of Truth

The AI is not the source of truth for this project.

The actual sources of truth are:

- Explicit requirements
- Domain/business rules
- Database constraints
- Tests
- Security controls
- Existing verified project behavior

When AI output conflicts with any of the above, the source of truth wins.

When requirements are ambiguous or missing, state the ambiguity instead of inventing behavior.

The core system must remain correct without AI. Future AI-assisted features (forecasting, scheduling optimization) must consume this system's verified data, not replace it as the authority.
