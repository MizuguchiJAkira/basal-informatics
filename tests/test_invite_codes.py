"""Tests for the invite-code beta signup gate.

The Strecker site rejects /register without a valid unused code.
Basal stays open. These tests lock in both brands' behavior plus
the single-use contract (one code, one user, not reusable).
"""

import os
import sys
import tempfile
from datetime import datetime


_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="invite-test-", suffix=".db", delete=False
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

for _mod in list(sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        sys.modules.pop(_mod, None)

import pytest


@pytest.fixture(scope="module")
def strecker_app():
    # Import lazily inside the fixture so the module-level
    # sys.modules-poke above forces a clean load even when another
    # test file reset them after us.
    from web.app import create_app
    from db.models import db
    app = create_app(demo=False, site="strecker")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        db.create_all()
        yield app


def _import_models():
    """Fetch the currently-loaded model classes. Deferred so we don't
    cache stale references across test files that shuffle sys.modules."""
    from db.models import db, User, InviteCode
    return db, User, InviteCode


@pytest.fixture(autouse=True)
def _clean_rows(strecker_app):
    """Wipe invite + user rows between tests so the shared SQLite DB
    doesn't leak state between assertions."""
    db, User, InviteCode = _import_models()
    with strecker_app.app_context():
        InviteCode.query.delete()
        User.query.delete()
        db.session.commit()
    yield


def _post_register(client, host="strecker.app", **form):
    return client.post(
        "/register",
        data=form,
        follow_redirects=False,
        base_url=f"https://{host}",
    )


def test_register_without_code_rejected(strecker_app):
    with strecker_app.test_client() as c:
        r = _post_register(c, email="hunter@example.com", password="hunterpass")
    assert r.status_code == 200
    assert b"invite" in r.data.lower()
    db, User, InviteCode = _import_models()
    assert User.query.filter_by(email="hunter@example.com").first() is None


def test_register_with_bogus_code_rejected(strecker_app):
    with strecker_app.test_client() as c:
        r = _post_register(
            c, email="hunter2@example.com", password="hunterpass",
            invite_code="NOT-A-REAL-CODE",
        )
    assert r.status_code == 200
    assert b"valid" in r.data.lower()
    db, User, InviteCode = _import_models()
    assert User.query.filter_by(email="hunter2@example.com").first() is None


def test_register_with_valid_code_succeeds_and_marks_used(strecker_app):
    db, User, InviteCode = _import_models()
    inv = InviteCode(code="STREK-ABCD1234", intended_for="test")
    db.session.add(inv)
    db.session.commit()

    with strecker_app.test_client() as c:
        r = _post_register(
            c, email="hunter3@example.com", password="hunterpass",
            display_name="Hunter",
            invite_code="STREK-ABCD1234",
        )
    assert r.status_code in (302, 303), r.data[:400]
    user = User.query.filter_by(email="hunter3@example.com").first()
    assert user is not None
    inv_fresh = InviteCode.query.filter_by(code="STREK-ABCD1234").first()
    assert inv_fresh.is_used
    assert inv_fresh.used_by_user_id == user.id
    assert inv_fresh.used_at is not None


def test_used_code_cannot_be_redeemed_twice(strecker_app):
    db, User, InviteCode = _import_models()
    inv = InviteCode(
        code="STREK-USED1234",
        used_at=datetime.utcnow(),
        used_by_user_id=None,
    )
    db.session.add(inv)
    db.session.commit()

    with strecker_app.test_client() as c:
        r = _post_register(
            c, email="second@example.com", password="secondpass",
            invite_code="STREK-USED1234",
        )
    assert r.status_code == 200
    assert b"already been used" in r.data.lower()
    assert User.query.filter_by(email="second@example.com").first() is None


def test_code_normalization_upper_and_whitespace(strecker_app):
    """Codes are case-insensitive + strip surrounding whitespace."""
    db, User, InviteCode = _import_models()
    inv = InviteCode(code="STREK-LOWER123")
    db.session.add(inv)
    db.session.commit()

    with strecker_app.test_client() as c:
        r = _post_register(
            c, email="case@example.com", password="casepass",
            invite_code="  strek-lower123 \n",
        )
    assert r.status_code in (302, 303), r.data[:400]
    assert User.query.filter_by(email="case@example.com").first() is not None


def test_basal_register_stays_open(strecker_app):
    """Basal site does not require an invite (same process, host-routed)."""
    db, User, InviteCode = _import_models()
    with strecker_app.test_client() as c:
        r = _post_register(
            c, host="basal.eco",
            email="owner@basal.eco.test", password="ownerpass",
        )
    assert r.status_code in (302, 303), r.data[:400]
    assert User.query.filter_by(email="owner@basal.eco.test").first() is not None


def test_code_via_query_string_autofills(strecker_app):
    """?code=XYZ in GET /register pre-fills the invite_code field."""
    with strecker_app.test_client() as c:
        r = c.get(
            "/register?code=STREK-URLCODE1",
            base_url="https://strecker.app",
        )
    assert r.status_code == 200
    assert b"STREK-URLCODE1" in r.data
