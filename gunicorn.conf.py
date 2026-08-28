"""Gunicorn configuration.

An unset worker count defaults to Gunicorn's own default of 1, which
gives this application no real request concurrency in production (and
made the Phase 1 load test unable to exercise concurrency at all against
a single-worker process). ``WEB_CONCURRENCY`` is Heroku/Gunicorn's
already-conventional env var name for this, so no new naming convention
is introduced.
"""

import os

workers = int(os.environ.get("WEB_CONCURRENCY", 3))
