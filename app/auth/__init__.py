"""Authentication and authorization core.

This package holds framework-agnostic auth building blocks (password
hashing, access scoping, redirect/decorator helpers, login business logic)
used by ``app.routes.auth`` and, in later milestones, by every other
route module that needs to enforce organizational scope.
"""
