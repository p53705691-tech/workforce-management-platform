"""Tests for Flask CLI commands registered in app.cli.

Only the production guard on ``seed demo-scenario`` is covered here: the
full seeding scenario is a large, additive, order-dependent script meant
for manual review (see its own docstring), not something this suite
re-verifies row by row.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.route


def test_seed_demo_scenario_refuses_to_run_with_flask_env_production(app, monkeypatch):
    """Security-review finding: this command provisions several manager-
    role accounts sharing one password and deletes real attendance rows,
    guarded only by "no Warehouse department yet" — not "is this a demo
    org". It must never run against a production configuration.
    """
    monkeypatch.setenv("FLASK_ENV", "production")

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["seed", "demo-scenario", "--organization", "does-not-exist"]
    )

    assert result.exit_code != 0
    assert "production configuration" in result.output


def test_seed_demo_scenario_guard_survives_the_real_flask_cli():
    """Regression test for a real bug caught manually, not by the test
    above: Flask's own CLI machinery (``ScriptInfo.load_app``, used by
    the actual ``flask`` command but *not* by ``app.test_cli_runner()``)
    unconditionally overwrites ``app.debug``/``app.config['DEBUG']``
    from the unrelated ``FLASK_DEBUG`` env var on every load. The
    original guard checked ``current_app.debug``, which read ``False``
    — and silently blocked every real invocation — even with
    ``FLASK_ENV=development`` set, because ``app.test_cli_runner()``
    never exercises that code path and so never caught it. This test
    shells out to the real ``flask`` executable specifically to close
    that gap.
    """
    env = {**os.environ, "FLASK_APP": "wsgi:app", "FLASK_ENV": "development"}
    # Route this subprocess at the test database, not a real dev one:
    # DevelopmentConfig reads DATABASE_URL, not TEST_DATABASE_URL.
    if "TEST_DATABASE_URL" in env:
        env["DATABASE_URL"] = env["TEST_DATABASE_URL"]
    result = subprocess.run(
        [sys.executable, "-m", "flask", "seed", "demo-scenario", "--organization", "does-not-exist"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Must fail because the organization doesn't exist -- *not* because
    # the production guard misfired (that specific message must be
    # absent) or because of an unrelated crash. click.ClickException
    # writes to stderr, not stdout.
    assert result.returncode != 0
    assert "production configuration" not in result.stderr
    assert "No organization found" in result.stderr
