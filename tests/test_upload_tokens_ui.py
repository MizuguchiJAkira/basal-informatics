"""Owner-facing UI for upload-token minting and revocation.

Thin page at /properties/<pid>/upload-tokens that wraps the existing
/api/properties/<pid>/upload-tokens JSON API. These tests assert:

  - The page renders 200 for the parcel owner.
  - It includes the mint form, a tokens table, and points the JS
    at the correct API base.
  - The API the page calls actually mints + lists + revokes, end to
    end (so a wiring regression anywhere in the loop fails here).
  - A non-owner who authenticates as someone else gets 404.
  - The upload page links to the new tokens page.
"""

import json
import os
import tempfile

import pytest


_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-tokui-", suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def ctx():
    from web.app import create_app
    from db.models import db, Property, User
    app = create_app(demo=True, site="strecker")
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        owner = User.query.filter_by(email="demo@strecker.app").first()
        if owner is None:
            owner = User(email="demo@strecker.app", is_owner=True,
                         password_hash="x")
            db.session.add(owner); db.session.commit()
        parcel = Property.query.filter_by(name="TokUI Parcel").first()
        if parcel is None:
            b = {"type": "Feature", "geometry": {"type": "Polygon",
                 "coordinates": [[[-96.5, 30.5], [-96.5, 30.6],
                                  [-96.4, 30.6], [-96.4, 30.5],
                                  [-96.5, 30.5]]]}}
            parcel = Property(
                user_id=owner.id, name="TokUI Parcel",
                county="Brazos", state="TX", acreage=200,
                boundary_geojson=json.dumps(b), crop_type="corn")
            db.session.add(parcel); db.session.commit()
        pid = parcel.id
    yield app, app.test_client(), pid


def test_page_renders_for_owner(ctx):
    _, c, pid = ctx
    r = c.get(f"/properties/{pid}/upload-tokens")
    assert r.status_code == 200, r.data
    html = r.get_data(as_text=True)
    # Mint form
    assert 'id="mint-form"' in html
    assert 'name="label"' in html
    assert 'name="email_hint"' in html
    assert 'name="uses"' in html
    assert 'name="ttl_days"' in html
    # Tokens table shell
    assert 'id="tokens-table"' in html
    assert 'id="tokens-body"' in html
    # JS points at the right API base — PROPERTY_ID is interpolated,
    # so check for the pieces the script concatenates at runtime.
    assert "/api/properties/" in html
    assert "/upload-tokens" in html
    assert f"const PROPERTY_ID = {pid};" in html


def test_page_404_for_non_owner(ctx):
    """A logged-in user who doesn't own the parcel gets 404, not the page."""
    app, _, pid = ctx
    from db.models import db, User
    with app.app_context():
        other = User.query.filter_by(email="other@strecker.app").first()
        if other is None:
            other = User(email="other@strecker.app",
                         password_hash="x", is_owner=False)
            db.session.add(other); db.session.commit()
        other_id = other.id

    # Fresh client, log in manually as the non-owner.
    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(other_id)
    r = c.get(f"/properties/{pid}/upload-tokens")
    assert r.status_code == 404


def test_mint_list_revoke_round_trip(ctx):
    """The page is thin — but the flow it wraps must work end to end."""
    _, c, pid = ctx
    api = f"/api/properties/{pid}/upload-tokens"

    # Mint
    r1 = c.post(api, json={"label": "UI round-trip",
                           "email_hint": "ui@example.test",
                           "uses": 5, "ttl_days": 14})
    assert r1.status_code == 201, r1.data
    minted = r1.get_json()
    tok = minted["token"]
    assert minted["share_url"].endswith(tok)

    # List — the new token must appear
    r2 = c.get(api)
    assert r2.status_code == 200
    toks = r2.get_json()["tokens"]
    match = [t for t in toks if t["token"] == tok]
    assert match, "freshly minted token missing from list"
    assert match[0]["label"] == "UI round-trip"
    assert match[0]["revoked"] is False

    # Revoke
    r3 = c.delete(f"{api}/{tok}")
    assert r3.status_code == 200
    assert r3.get_json()["revoked"] is True

    # List again — token is now revoked
    r4 = c.get(api)
    toks = r4.get_json()["tokens"]
    match = [t for t in toks if t["token"] == tok]
    assert match and match[0]["revoked"] is True


def test_upload_page_links_to_tokens_page(ctx):
    """The owner must be able to discover the tokens page from
    the parcel's upload page."""
    _, c, pid = ctx
    r = c.get(f"/properties/{pid}/upload")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f"/properties/{pid}/upload-tokens" in html
