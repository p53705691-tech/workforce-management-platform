# Workforce Management Platform

A production-oriented Workforce Management Platform built with Flask and
PostgreSQL. See `CLAUDE.md` for the full project overview, product
philosophy, and architecture rules.

## Requirements

- Python 3.11+
- PostgreSQL 14+ (with the `btree_gist` and `citext` extensions available)

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file and fill in real values:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set `SECRET_KEY`, `DATABASE_URL`, and
   `TEST_DATABASE_URL` for your local setup. `.env` is gitignored and must
   never be committed.

4. Apply database migrations:

   ```bash
   flask db upgrade
   ```

5. Run the test suite:

   ```bash
   pytest
   ```

## Running the app locally

```bash
flask run
```

The health check endpoint is available at `GET /healthz` and returns
`{"status": "ok"}`.

## Project layout

- `app/` — Flask application code (routes, services, models)
- `app/models/` — SQLAlchemy models
- `migrations/` — Alembic migrations
- `templates/` — Jinja templates
- `static/` — CSS and vanilla JavaScript
- `tests/` — pytest tests
