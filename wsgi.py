from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

app = create_app()

# Only applied when TRUST_PROXY is set (ProductionConfig — see
# app/config.py), i.e. only when this process is actually deployed
# behind the documented Nginx reverse proxy. Without this, Werkzeug
# reads the connecting socket's address for every request, which behind
# a proxy is always Nginx's own address — silently making per-IP rate
# limiting (app.extensions.limiter) apply to the whole site as one
# shared counter instead of per real client, and corrupting the audit
# log's ip_address column (app.services.audit.record) for every entry.
# x_for=1, x_proto=1: trust exactly one hop of X-Forwarded-For/-Proto,
# matching a single Nginx reverse proxy in front of this app — not a
# chain of multiple proxies. Applying this to a deployment with no
# proxy in front would let a client spoof its own source IP via a
# forged X-Forwarded-For header, which is exactly why it's gated behind
# TRUST_PROXY rather than always on.
if app.config.get("TRUST_PROXY"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
