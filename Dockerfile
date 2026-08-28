FROM python:3.14-slim

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

# This image is the production deployment path (Gunicorn behind Nginx —
# see CLAUDE.md's Production stack). FLASK_ENV unset defaults to
# DevelopmentConfig (DEBUG=True, non-secure session cookies, no HSTS,
# no fail-fast SECRET_KEY/DATABASE_URL checks — see app/__init__.py and
# app/config.py), which must never be what a built container runs with
# by default. An operator who genuinely wants a containerized dev
# environment can still override this via docker-compose's
# `environment:` (which takes precedence over both this and env_file).
ENV FLASK_ENV=production

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "-b", "0.0.0.0:8000", "wsgi:app"]
