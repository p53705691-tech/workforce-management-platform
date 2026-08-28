"""Concurrent HTTP load test against a real running server.

Unlike ``scripts/benchmark_dashboard.py`` (in-process, via
``app.test_client()``), this fires real HTTP requests at a running
``gunicorn``/dev server — the actual concurrency test for
``gunicorn.conf.py``'s worker count. stdlib only (``urllib.request`` +
``concurrent.futures.ThreadPoolExecutor``), no ``requests`` dependency.

Setup
-----
1. Seed a benchmark organization (see ``app/cli.py``)::

       flask seed benchmark --organization bench-50 --employees 50

2. Run the server for real, e.g.::

       WEB_CONCURRENCY=3 gunicorn -c gunicorn.conf.py -b 127.0.0.1:8000 wsgi:app

3. Run this script against it::

       python scripts/load_test.py --org bench-50
       python scripts/load_test.py --org bench-50 --base-url http://127.0.0.1:8000 \\
           --concurrency 5 20

Each simulated "user" logs in independently (own cookie jar + CSRF
token, extracted from rendered HTML the same way the app's own forms
work — see ``app/extensions.py``'s ``csrf``: this app has no
fetch/AJAX, so every state-changing request is a real HTML form post)
as the org's employee login, then hits every endpoint below. Login,
Admin/Manager/Employee Dashboard, and both reports are read-only and
safe to repeat; Clock In/Out and Leave request are real state changes,
so expect some of those to legitimately fail under concurrency (e.g. an
employee who is already clocked in) — that is itself useful load-test
signal (a wrong error rate here would mean the DB's own exclusion
constraints aren't holding), not a bug in this script.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import re
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request

BENCHMARK_PASSWORD = "Benchmark-Seed-Only-2026!"
CSRF_RE = re.compile(r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"')
CLOCK_OUT_ACTION_RE = re.compile(r'/attendance/(\d+)/clock-out')


class LoadTestSession:
    """One simulated user: its own cookie jar, so concurrent sessions
    never share auth state.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self.opener.addheaders = [("User-Agent", "wfm-load-test/1.0")]

    def request(self, method: str, path: str, data: dict | None = None):
        url = f"{self.base_url}{path}"
        body = None
        headers = {}
        if data is not None:
            body = "&".join(
                f"{urllib.parse.quote_plus(k)}={urllib.parse.quote_plus(str(v))}"
                for k, v in data.items()
            ).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=15) as response:
                return response.status, response.read().decode(errors="replace")
        except urllib.error.HTTPError as error:
            # A redirect (302) after a POST is the normal success path for
            # every form in this app -- urllib follows it automatically,
            # so an HTTPError here means a genuine 4xx/5xx.
            return error.code, error.read().decode(errors="replace")

    def get(self, path: str):
        return self.request("GET", path)

    def post_form(self, path: str, csrf_source_body: str, fields: dict):
        match = CSRF_RE.search(csrf_source_body)
        if match:
            fields = {**fields, "csrf_token": match.group(1)}
        return self.request("POST", path, fields)


def login(base_url: str, email: str) -> LoadTestSession | None:
    session = LoadTestSession(base_url)
    status, body = session.get("/login")
    if status != 200:
        return None
    status, body = session.post_form(
        "/login", body, {"email": email, "password": BENCHMARK_PASSWORD}
    )
    return session if status in (200, 302) else None


def _emails_for_org(slug: str) -> dict[str, str]:
    return {
        "admin": f"admin@{slug}.bench.local",
        "manager": f"manager.ops@{slug}.bench.local",
        "employee": f"employee@{slug}.bench.local",
    }


def _timed(fn):
    started = time.perf_counter()
    try:
        status, body = fn()
        ok = 200 <= status < 400
        return (time.perf_counter() - started) * 1000, ok, body
    except Exception:
        return (time.perf_counter() - started) * 1000, False, ""


def run_one_user(base_url: str, org_slug: str) -> dict[str, list[tuple[float, bool]]]:
    """One simulated user's full workflow. Returns endpoint label ->
    list of (latency_ms, ok) for every request that endpoint made.
    """
    results: dict[str, list[tuple[float, bool]]] = {}

    def record(label, fn):
        latency, ok, body = _timed(fn)
        results.setdefault(label, []).append((latency, ok))
        return body

    emails = _emails_for_org(org_slug)

    admin = login(base_url, emails["admin"])
    if admin:
        record("Admin Dashboard", lambda: admin.get("/dashboard"))
        record("Overtime Report", lambda: admin.get("/reports/overtime"))
        record("Hours Trend Report", lambda: admin.get("/reports/hours-trend"))

    manager = login(base_url, emails["manager"])
    if manager:
        record("Manager Dashboard", lambda: manager.get("/dashboard"))

    employee = login(base_url, emails["employee"])
    if employee:
        record("Employee Dashboard", lambda: employee.get("/dashboard"))

        attendance_body = record(
            "Attendance List", lambda: employee.get("/attendance")
        )
        record(
            "Clock In",
            lambda: employee.post_form("/attendance/clock-in", attendance_body, {}),
        )

        # The clock-out form only renders on the Employee Dashboard (see
        # templates/dashboard/employee.html), not the Attendance list
        # page, per this app's "one unmistakable primary action" design.
        _status, after_clock_in_body = employee.get("/dashboard")
        entry_match = CLOCK_OUT_ACTION_RE.search(after_clock_in_body)
        if entry_match:
            entry_id = entry_match.group(1)
            record(
                "Clock Out",
                lambda: employee.post_form(
                    f"/attendance/{entry_id}/clock-out", after_clock_in_body, {}
                ),
            )

        record("Leave List", lambda: employee.get("/leave"))

    if admin:
        pending_body = admin.get("/leave?status=pending")[1]
        approve_match = re.search(r'/leave/(\d+)/approve', pending_body)
        if approve_match:
            leave_id = approve_match.group(1)
            record(
                "Leave Approve",
                lambda: admin.post_form(
                    f"/leave/{leave_id}/approve", pending_body, {}
                ),
            )

    return results


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def run_at_concurrency(base_url: str, org_slug: str, concurrency: int) -> None:
    print(f"\n=== concurrency={concurrency} ===")
    merged: dict[str, list[tuple[float, bool]]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(run_one_user, base_url, org_slug) for _ in range(concurrency)
        ]
        for future in futures:
            for label, samples in future.result().items():
                merged.setdefault(label, []).extend(samples)

    headers = ["Endpoint", "Requests", "Errors", "p50 (ms)", "p95 (ms)"]
    rows = []
    for label, samples in merged.items():
        latencies = [latency for latency, _ok in samples]
        errors = sum(1 for _latency, ok in samples if not ok)
        rows.append(
            [
                label,
                str(len(samples)),
                f"{errors} ({100 * errors / len(samples):.0f}%)",
                f"{_percentile(latencies, 50):.1f}",
                f"{_percentile(latencies, 95):.1f}",
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--org", required=True, help="Benchmark organization slug (see app/cli.py)."
    )
    parser.add_argument(
        "--concurrency", type=int, nargs="+", default=[5, 20],
        help="One or more concurrency levels to run sequentially.",
    )
    args = parser.parse_args()

    for level in args.concurrency:
        run_at_concurrency(args.base_url, args.org, level)


if __name__ == "__main__":
    main()
