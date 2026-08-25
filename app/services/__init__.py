"""Service layer package.

Business logic lives here, one module per domain area (e.g.
``departments``, ``employees``). Routes call into these modules rather
than querying the database directly, and every public function enforces
its own authorization from an ``AccessScope`` instead of trusting the
route to have already checked it.
"""
