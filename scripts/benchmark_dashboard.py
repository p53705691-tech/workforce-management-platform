"""Query-count and wall-clock benchmark for the dashboard/report pages.

Purpose
-------
Phase 1 of the production-hardening plan fixed an N+1 query pattern in
``reports.overtime_summary``/``reports.hours_trend`` (see
``app.services.labor_cost.range_cost_for_employees`` and
``app.services.working_hours.worked_seconds_by_range_for_employees``).
This script produces the actual before/after evidence for that fix —
real query counts and latency, not estimates — by hitting the pages
that changed (plus every dashboard variant, for context) at a range of
organization sizes.

Setup
-----
1. Seed one or more benchmark organizations first, via the CLI command
   this script is designed to pair with (see ``app/cli.py``)::

       flask seed benchmark --organization bench-10  --employees 10
       flask seed benchmark --organization bench-50  --employees 50
       flask seed benchmark --organization bench-100 --employees 100
       flask seed benchmark --organization bench-250 --employees 250
       flask seed benchmark --organization bench-500 --employees 500

   Each size gets its own dedicated organization (the seed command
   refuses to re-seed an organization that already has data), and every
   account it creates shares one fixed password
   (``app.cli._BENCHMARK_PASSWORD`` — see that command's docstring for
   why it's fixed rather than randomized).

2. Run this script with the same ``DATABASE_URL``/``FLASK_ENV`` the
   seed command used (so it reads the same database), e.g.::

       python scripts/benchmark_dashboard.py
       python scripts/benchmark_dashboard.py bench-10 bench-50

   With no arguments, the default matrix (``bench-10``, ``bench-50``,
   ``bench-100``, ``bench-250``, ``bench-500``) is used; an org slug
   that hasn't actually been seeded yet is skipped with a warning
   printed to stderr, not a hard failure, so this can be run against
   however many sizes are actually available at the time.

How it works
------------
Uses ``app.test_client()`` (WSGI-level requests, no real network) so
this measures the application layer itself, not network/HTTP overhead —
that's what ``scripts/load_test.py`` is for, against a real running
server. Query counting is a SQLAlchemy ``before_cursor_execute`` engine
event listener (no new dependency): every statement actually sent to
Postgres for a request increments a counter, reset before each request
via ``_count_queries``.
"""

from __future__ import annotations

import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Allow running as `python scripts/benchmark_dashboard.py` from anywhere,
# without needing the repo root already on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db
from app.models.organization import Organization
from app.models.user import User

DEFAULT_ORG_SLUGS = ["bench-10", "bench-50", "bench-100", "bench-250", "bench-500"]

# Must match app.cli._BENCHMARK_PASSWORD -- every login `flask seed
# benchmark` creates shares this one fixed password.
BENCHMARK_PASSWORD = "Benchmark-Seed-Only-2026!"

# (page label, path, role to log in as) -- role selects which of the
# three logins `flask seed benchmark` creates for the org
# (admin@/manager.ops@/employee@<slug>.bench.local) is used for that row.
_CSRF_INPUT_RE = re.compile(
    r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"'
)

PAGES = [
    ("Admin Dashboard", "/dashboard", "admin"),
    ("Manager Dashboard", "/dashboard", "manager"),
    ("Employee Dashboard", "/dashboard", "employee"),
    ("Overtime Report", "/reports/overtime", "admin"),
    ("Hours Trend Report", "/reports/hours-trend", "admin"),
]


class _QueryCounter:
    """Counts every statement Postgres actually executes, process-wide,
    via a SQLAlchemy core event -- reset per request so each page's own
    query count is isolated from setup/login queries around it.
    """

    def __init__(self) -> None:
        self.count = 0
        event.listen(Engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

    def reset(self) -> None:
        self.count = 0


@contextmanager
def _measure(counter: _QueryCounter):
    counter.reset()
    started = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - started) * 1000
    _measure.last_result = (counter.count, elapsed_ms)


def _login(client, email: str) -> bool:
    """Log ``client`` in as ``email`` (fixed benchmark password).
    Returns ``False`` (without raising) if the login page/credentials
    don't work, so one missing login doesn't abort the whole run.
    """
    login_page = client.get("/login")
    if login_page.status_code != 200:
        return False
    body = login_page.data.decode()
    match = _CSRF_INPUT_RE.search(body)
    csrf_token = match.group(1) if match else None

    data = {"email": email, "password": BENCHMARK_PASSWORD}
    if csrf_token:
        data["csrf_token"] = csrf_token
    response = client.post("/login", data=data, follow_redirects=False)
    return response.status_code in (302, 303)


def _emails_for_org(slug: str) -> dict[str, str]:
    return {
        "admin": f"admin@{slug}.bench.local",
        "manager": f"manager.ops@{slug}.bench.local",
        "employee": f"employee@{slug}.bench.local",
    }


def _org_employee_count(organization_id: int) -> int:
    from app.models.employee import Employee

    return (
        db.session.query(Employee.id)
        .filter(Employee.organization_id == organization_id)
        .count()
    )


def benchmark_org(app, slug: str, counter: _QueryCounter) -> list[dict] | None:
    with app.app_context():
        organization = (
            db.session.query(Organization).filter(Organization.slug == slug).first()
        )
        if organization is None:
            print(f"warning: organization {slug!r} not found -- skipping "
                  f"(seed it first with `flask seed benchmark --organization "
                  f"{slug} --employees N`)", file=sys.stderr)
            return None
        employee_count = _org_employee_count(organization.id)
        emails = _emails_for_org(slug)

    rows = []
    for label, path, role in PAGES:
        email = emails[role]
        client = app.test_client()
        with app.app_context():
            logged_in = _login(client, email)
        if not logged_in:
            print(f"warning: could not log in as {email!r} for {slug!r} -- "
                  f"skipping {label!r}", file=sys.stderr)
            continue

        with app.app_context(), _measure(counter):
            response = client.get(path)
        query_count, elapsed_ms = _measure.last_result

        rows.append(
            {
                "org": slug,
                "employees": employee_count,
                "page": label,
                "status": response.status_code,
                "queries": query_count,
                "ms": elapsed_ms,
            }
        )
    return rows


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("No results (no benchmark organizations were found).")
        return

    headers = ["Org", "Employees", "Page", "Status", "Queries", "Time (ms)"]
    widths = [len(h) for h in headers]
    formatted = []
    for row in rows:
        cells = [
            row["org"],
            str(row["employees"]),
            row["page"],
            str(row["status"]),
            str(row["queries"]),
            f"{row['ms']:.1f}",
        ]
        formatted.append(cells)
        widths = [max(w, len(c)) for w, c in zip(widths, cells)]

    def _print_row(cells):
        print("  ".join(cell.ljust(width) for cell, width in zip(cells, widths)))

    _print_row(headers)
    _print_row(["-" * w for w in widths])
    for cells in formatted:
        _print_row(cells)


def main() -> None:
    org_slugs = sys.argv[1:] or DEFAULT_ORG_SLUGS

    app = create_app(app_config_name())
    counter = _QueryCounter()

    all_rows: list[dict] = []
    for slug in org_slugs:
        rows = benchmark_org(app, slug, counter)
        if rows:
            all_rows.extend(rows)

    _print_table(all_rows)


def app_config_name() -> str:
    """Which config to boot with: whatever FLASK_ENV already says
    (defaulting to "development", same default ``create_app`` itself
    uses), so this reads the same database `flask seed benchmark` wrote
    to. Never "testing" -- that config points at TEST_DATABASE_URL, a
    different database than whatever the seed command used.
    """
    import os

    config_name = os.environ.get("FLASK_ENV", "development")
    if config_name == "testing":
        raise SystemExit(
            "FLASK_ENV=testing points at TEST_DATABASE_URL, not the "
            "database `flask seed benchmark` seeded. Unset FLASK_ENV or "
            "set it to development/production before running this script."
        )
    return config_name


if __name__ == "__main__":
    main()
