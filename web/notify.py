"""Email notification shim — provider-agnostic transport.

Lets the rest of the app say ``send_email(to, subject, body)`` without
caring whether it's going out through Postmark, SES, SMTP, or just
being printed to stdout in dev.

Why build this instead of reaching for Flask-Mail / a vendor SDK?

  * Zero runtime dependencies beyond stdlib for three of the four
    backends — Postmark uses urllib, SMTP uses smtplib, console is
    just print(). Only SES needs boto3, which we already carry for
    DO Spaces.
  * The landowner invite is our first user-facing email, and more
    will come (report-ready pings, monthly field-ops digests). Having
    a single ``send_email`` seam now means swapping providers later
    is a one-env-var change, not a code change.
  * Best-effort delivery: every backend returns a bool rather than
    raising. The token-mint endpoint cares whether the email went
    out, but a send failure must never roll back the token — the
    landowner can always be sent the link by hand.

Backends are selected via ``EMAIL_PROVIDER`` (``console`` default).
Each backend reads its own env vars only when it's the active one,
so you don't need Postmark creds present to run the SMTP backend.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _send_console(to: str, subject: str, body_text: str,
                  body_html: Optional[str]) -> bool:
    """Print the email to stdout — dev default, never hits the network."""
    stream = sys.stdout
    stream.write("=" * 72 + "\n")
    stream.write(f"[notify.console] To: {to}\n")
    stream.write(f"[notify.console] Subject: {subject}\n")
    stream.write("-" * 72 + "\n")
    stream.write(body_text + "\n")
    if body_html:
        stream.write("-- html --\n")
        stream.write(body_html + "\n")
    stream.write("=" * 72 + "\n")
    stream.flush()
    return True


def _send_postmark(to: str, subject: str, body_text: str,
                   body_html: Optional[str]) -> bool:
    token = os.environ.get("POSTMARK_SERVER_TOKEN", "")
    sender = os.environ.get("EMAIL_FROM", "noreply@basalinformatics.com")
    if not token:
        logger.error("POSTMARK_SERVER_TOKEN not set; dropping email to %s", to)
        return False
    payload = {
        "From": sender, "To": to, "Subject": subject,
        "TextBody": body_text,
        "MessageStream": os.environ.get("POSTMARK_MESSAGE_STREAM", "outbound"),
    }
    if body_html:
        payload["HtmlBody"] = body_html
    req = urllib.request.Request(
        "https://api.postmarkapp.com/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        logger.error("Postmark HTTPError %s for %s: %s", e.code, to, e.read())
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("Postmark send failed for %s: %s", to, e)
        return False


def _send_ses(to: str, subject: str, body_text: str,
              body_html: Optional[str]) -> bool:
    sender = os.environ.get("EMAIL_FROM", "noreply@basalinformatics.com")
    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        import boto3  # type: ignore
    except ImportError:
        logger.error("boto3 not installed; cannot send SES email")
        return False
    try:
        client = boto3.client("ses", region_name=region)
        body = {"Text": {"Data": body_text}}
        if body_html:
            body["Html"] = {"Data": body_html}
        client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to]},
            Message={"Subject": {"Data": subject}, "Body": body},
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("SES send failed for %s: %s", to, e)
        return False


def _send_smtp(to: str, subject: str, body_text: str,
               body_html: Optional[str]) -> bool:
    host = os.environ.get("SMTP_HOST", "localhost")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_STARTTLS", "1") == "1"
    sender = os.environ.get("EMAIL_FROM", "noreply@basalinformatics.com")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            if use_tls:
                s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("SMTP send failed for %s: %s", to, e)
        return False


_BACKENDS = {
    "console": _send_console,
    "postmark": _send_postmark,
    "ses": _send_ses,
    "smtp": _send_smtp,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, body_text: str,
               body_html: Optional[str] = None) -> bool:
    """Route an email through the configured provider.

    Returns True on apparent success, False otherwise. Never raises —
    delivery is best-effort and callers should not make their own
    success depend on email going through.
    """
    provider = os.environ.get("EMAIL_PROVIDER", "console").lower().strip()
    backend = _BACKENDS.get(provider)
    if backend is None:
        logger.warning("Unknown EMAIL_PROVIDER %r; falling back to console",
                       provider)
        backend = _send_console
    if not to or "@" not in to:
        logger.warning("send_email: invalid recipient %r", to)
        return False
    try:
        return bool(backend(to, subject, body_text, body_html))
    except Exception as e:  # noqa: BLE001
        logger.exception("send_email: backend %s raised: %s", provider, e)
        return False


def send_upload_invite(to_email: str, parcel_name: str, share_url: str,
                       expires_at_iso: Optional[str],
                       label: Optional[str] = None) -> bool:
    """Build and send the landowner's upload-invite email.

    Subject names the parcel so it survives mobile-client truncation;
    body explains what the link does and when it expires, because a
    bare URL with no context reads like phishing.
    """
    subject = f"Upload your trail-cam photos for {parcel_name}"
    expiry_line = (f"This link expires on {expires_at_iso}."
                   if expires_at_iso else "")
    label_line = f"\nReference: {label}\n" if label else ""
    body_text = (
        f"Hi,\n\n"
        f"Basal Informatics is processing trail-cam data for "
        f"{parcel_name}. Use the link below to upload your SD-card "
        f"zip. No account needed — just open the page and pick "
        f"the file.\n\n"
        f"{share_url}\n\n"
        f"{expiry_line}{label_line}\n"
        f"If you didn't expect this message, ignore it — the link "
        f"does nothing without a zip to upload.\n\n"
        f"— Basal Informatics\n"
    )
    body_html = (
        f"<p>Hi,</p>"
        f"<p>Basal Informatics is processing trail-cam data for "
        f"<strong>{parcel_name}</strong>. Use the link below to "
        f"upload your SD-card zip. No account needed — just open "
        f"the page and pick the file.</p>"
        f'<p><a href="{share_url}">{share_url}</a></p>'
        f"<p>{expiry_line}</p>"
        + (f"<p>Reference: {label}</p>" if label else "")
        + "<p style='color:#666'>If you didn't expect this message, "
          "ignore it — the link does nothing without a zip to upload."
          "</p>"
    )
    return send_email(to_email, subject, body_text, body_html)
