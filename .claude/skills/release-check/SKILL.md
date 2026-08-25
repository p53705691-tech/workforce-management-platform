---
name: release-check
description: Perform a final production-readiness check before deployment.
---

# Release Check

Verify:

## Code

- No debug code
- No TODOs blocking release
- No unnecessary files
- No accidental changes

## Security

- No secrets
- Authentication works
- Authorization works
- CSRF protection is appropriate
- Sensitive data is protected

## Database

- Migrations exist
- Migrations are valid
- Constraints are correct

## Tests

- Relevant tests pass
- Regression tests exist

## Configuration

- Production environment variables are defined
- Debug mode is disabled
- Secure configuration is used

## Final

Inspect the complete diff.

Do not claim release readiness without verification.
