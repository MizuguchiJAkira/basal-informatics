"""Email notification shim — backend routing + mint-endpoint integration.

The console backend is the dev default; it must never touch the
network. The three real backends (Postmark / SES / SMTP) are tested
with the transport mocked, so these tests run offline.

End of file: an integration test that mints a token with
``send_email: true`` and confirms the helper is invoked.
"""

import io
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# --- Test DB bootstrap (mirrors tests/test_token_uploads.py) -----------------

_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-notify-", suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def test_console_backend_prints_and_succeeds(monkeypatch, capsys):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    ok = notify.send_email(
        "landowner@example.test", "Hello", "plain body",
        body_html="<p>rich</p>",
    )
    assert ok is True
    out = capsys.readouterr().out
    assert "landowner@example.test" in out
    assert "Hello" in out
    assert "plain body" in out
    assert "<p>rich</p>" in out


def test_invalid_recipient_rejected(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    assert notify.send_email("", "s", "b") is False
    assert notify.send_email("not-an-email", "s", "b") is False


def test_unknown_provider_falls_back_to_console(monkeypatch, capsys):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    ok = notify.send_email("a@b.test", "subj", "body")
    assert ok is True
    assert "a@b.test" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Postmark
# ---------------------------------------------------------------------------

def test_postmark_backend_posts_with_token(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "postmark")
    monkeypatch.setenv("POSTMARK_SERVER_TOKEN", "pmk-secret")
    monkeypatch.setenv("EMAIL_FROM", "ops@basalinformatics.com")

    captured = {}

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    with patch.object(notify.urllib.request, "urlopen", _fake_urlopen):
        ok = notify.send_email("a@b.test", "Sub", "Body", body_html="<b>h</b>")
    assert ok is True
    assert captured["url"] == "https://api.postmarkapp.com/email"
    # urllib normalizes header names to title-case
    hdrs = {k.lower(): v for k, v in captured["headers"].items()}
    assert hdrs.get("x-postmark-server-token") == "pmk-secret"
    assert captured["data"]["From"] == "ops@basalinformatics.com"
    assert captured["data"]["To"] == "a@b.test"
    assert captured["data"]["Subject"] == "Sub"
    assert captured["data"]["TextBody"] == "Body"
    assert captured["data"]["HtmlBody"] == "<b>h</b>"


def test_postmark_without_token_fails(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "postmark")
    monkeypatch.delenv("POSTMARK_SERVER_TOKEN", raising=False)
    assert notify.send_email("a@b.test", "s", "b") is False


# ---------------------------------------------------------------------------
# SES
# ---------------------------------------------------------------------------

def test_ses_backend_calls_boto3(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setenv("EMAIL_FROM", "ops@basalinformatics.com")

    fake_client = MagicMock()
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client

    with patch.dict(_sys.modules, {"boto3": fake_boto3}):
        ok = notify.send_email("a@b.test", "Sub", "Body", body_html="<i>h</i>")

    assert ok is True
    fake_boto3.client.assert_called_once()
    args, kwargs = fake_client.send_email.call_args
    assert kwargs["Source"] == "ops@basalinformatics.com"
    assert kwargs["Destination"] == {"ToAddresses": ["a@b.test"]}
    assert kwargs["Message"]["Subject"]["Data"] == "Sub"
    assert kwargs["Message"]["Body"]["Text"]["Data"] == "Body"
    assert kwargs["Message"]["Body"]["Html"]["Data"] == "<i>h</i>"


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------

def test_smtp_backend_sends_via_smtplib(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("SMTP_STARTTLS", "1")
    monkeypatch.setenv("EMAIL_FROM", "ops@basalinformatics.com")

    fake_smtp_instance = MagicMock()
    fake_smtp_cls = MagicMock()
    fake_smtp_cls.return_value.__enter__.return_value = fake_smtp_instance

    with patch.object(notify.smtplib, "SMTP", fake_smtp_cls):
        ok = notify.send_email("a@b.test", "Sub", "Body", body_html="<p>x</p>")

    assert ok is True
    fake_smtp_cls.assert_called_once_with("smtp.example.test", 2525, timeout=10)
    fake_smtp_instance.starttls.assert_called_once()
    fake_smtp_instance.login.assert_called_once_with("user", "pw")
    fake_smtp_instance.send_message.assert_called_once()
    msg = fake_smtp_instance.send_message.call_args[0][0]
    assert msg["From"] == "ops@basalinformatics.com"
    assert msg["To"] == "a@b.test"
    assert msg["Subject"] == "Sub"


def test_smtp_backend_swallows_errors(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")

    def _boom(*a, **kw):
        raise OSError("connection refused")

    with patch.object(notify.smtplib, "SMTP", _boom):
        assert notify.send_email("a@b.test", "s", "b") is False


# ---------------------------------------------------------------------------
# send_upload_invite: subject + body shape
# ---------------------------------------------------------------------------

def test_send_upload_invite_builds_plausible_body(monkeypatch):
    from web import notify
    monkeypatch.setenv("EMAIL_PROVIDER", "console")

    captured = {}

    def _spy(to, subject, text, html=None):
        captured["to"] = to
        captured["subject"] = subject
        captured["text"] = text
        captured["html"] = html
        return True

    with patch.object(notify, "send_email", _spy):
        ok = notify.send_upload_invite(
            to_email="phil@matagorda-ag.test",
            parcel_name="Matagorda North",
            share_url="https://strecker.app/u/abc123",
            expires_at_iso="2026-07-18T00:00:00",
            label="Matagorda pilot",
        )

    assert ok is True
    assert captured["to"] == "phil@matagorda-ag.test"
    assert "Matagorda North" in captured["subject"]
    assert "https://strecker.app/u/abc123" in captured["text"]
    assert "2026-07-18" in captured["text"]
    assert "Matagorda pilot" in captured["text"]
    assert "https://strecker.app/u/abc123" in (captured["html"] or "")


# ---------------------------------------------------------------------------
# Mint endpoint integration: send_email=true fires the helper
# ---------------------------------------------------------------------------

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
        parcel = Property.query.filter_by(name="Notify Parcel").first()
        if parcel is None:
            b = {"type": "Feature", "geometry": {"type": "Polygon",
                 "coordinates": [[[-96.5,30.5],[-96.5,30.6],
                                  [-96.4,30.6],[-96.4,30.5],[-96.5,30.5]]]}}
            parcel = Property(
                user_id=owner.id, name="Notify Parcel",
                county="Brazos", state="TX", acreage=320,
                boundary_geojson=json.dumps(b), crop_type="corn")
            db.session.add(parcel); db.session.commit()
        pid = parcel.id
    yield app, app.test_client(), pid


def test_issue_token_sends_email_when_flag_set(ctx, monkeypatch):
    _, c, pid = ctx
    monkeypatch.setenv("EMAIL_PROVIDER", "console")

    calls = {}

    def _spy(**kwargs):
        calls.update(kwargs)
        return True

    with patch("web.notify.send_upload_invite", _spy):
        r = c.post(f"/api/properties/{pid}/upload-tokens",
                   json={"label": "invite test",
                         "email_hint": "phil@matagorda-ag.test",
                         "uses": 2, "ttl_days": 14,
                         "send_email": True})
    assert r.status_code == 201, r.data
    j = r.get_json()
    assert j["email_sent"] is True
    assert calls["to_email"] == "phil@matagorda-ag.test"
    assert calls["parcel_name"] == "Notify Parcel"
    assert calls["share_url"].endswith(j["token"])
    assert calls["label"] == "invite test"


def test_issue_token_without_send_email_skips(ctx):
    _, c, pid = ctx

    def _fail(**kwargs):
        raise AssertionError("send_upload_invite should not be called")

    with patch("web.notify.send_upload_invite", _fail):
        r = c.post(f"/api/properties/{pid}/upload-tokens",
                   json={"email_hint": "phil@matagorda-ag.test"})
    assert r.status_code == 201
    assert "email_sent" not in r.get_json()


def test_issue_token_send_email_failure_returns_201(ctx):
    _, c, pid = ctx

    with patch("web.notify.send_upload_invite", return_value=False):
        r = c.post(f"/api/properties/{pid}/upload-tokens",
                   json={"email_hint": "phil@matagorda-ag.test",
                         "send_email": True})
    assert r.status_code == 201
    j = r.get_json()
    assert j["email_sent"] is False
    assert "email_error" in j
    # token still minted
    assert j["token"]


def test_issue_token_send_email_without_hint_noop(ctx):
    _, c, pid = ctx

    def _fail(**kwargs):
        raise AssertionError("should not be called without email_hint")

    with patch("web.notify.send_upload_invite", _fail):
        r = c.post(f"/api/properties/{pid}/upload-tokens",
                   json={"send_email": True})
    assert r.status_code == 201
    assert "email_sent" not in r.get_json()
