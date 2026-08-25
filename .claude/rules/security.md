---
paths:
  - "app/**/*.py"
  - "templates/**/*.html"
  - "static/**/*.js"
---

# Security Rules

Treat all external input as untrusted.

Always enforce authorization on the server.

Never rely on:

- hidden UI elements
- disabled buttons
- frontend validation
- URL obscurity

Protect against:

- Broken Access Control
- IDOR
- SQL Injection
- XSS
- CSRF
- Session Abuse
- Privilege Escalation
- Sensitive Data Exposure
- Unsafe File Handling
- Insecure Redirects

Never:

- hard-code secrets
- log passwords
- log session tokens
- expose database credentials
- expose stack traces
- construct SQL using user-controlled strings

Use parameterized queries.

Validate input.

Escape untrusted output appropriately.

Every privileged operation must verify the user's role and organizational scope.

Prefer secure defaults.

Do not weaken security controls just to simplify development.

Security-sensitive changes should receive an explicit security review.
