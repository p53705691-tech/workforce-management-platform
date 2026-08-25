import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_select_1(db_session):
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_required_extensions_are_installed(db_session):
    installed = db_session.execute(
        text("SELECT extname FROM pg_extension")
    ).scalars().all()

    assert "btree_gist" in installed
    assert "citext" in installed
