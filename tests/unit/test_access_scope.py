import pytest

from app.auth.scope import AccessScope

pytestmark = pytest.mark.unit


def test_access_scope_holds_given_values():
    scope = AccessScope(
        user_id=1,
        organization_id=2,
        role="manager",
        department_ids=frozenset({3, 4}),
        employee_id=None,
    )

    assert scope.user_id == 1
    assert scope.organization_id == 2
    assert scope.role == "manager"
    assert scope.department_ids == frozenset({3, 4})
    assert scope.employee_id is None


def test_access_scope_is_frozen():
    scope = AccessScope(
        user_id=1,
        organization_id=2,
        role="admin",
        department_ids=frozenset(),
        employee_id=None,
    )

    with pytest.raises(AttributeError):
        scope.role = "employee"
