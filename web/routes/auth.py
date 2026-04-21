"""Authentication routes — register, login, logout.

GET/POST /login    — render login form, validate credentials
GET/POST /register — render register form, create user
GET      /logout   — log out, redirect to login
"""

from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from db.models import db, User, InviteCode


def _require_invite() -> bool:
    """Strecker gates signup on an invite code during beta. Basal does
    not. Per-request, keyed on active_site so the same process can run
    both brands."""
    active = getattr(current_app, "active_site", None)
    site = active() if callable(active) else current_app.config.get("SITE")
    return site == "strecker"

auth_bp = Blueprint("auth", __name__)


def _default_landing():
    """Return the appropriate post-login URL based on the active brand.

    Host-routed: hits against strecker.* land on /properties, hits
    against basal.* land on /owner/coverage. Falls back to the app's
    boot-time default if there's no request context.
    """
    active = getattr(current_app, "active_site", None)
    site = active() if callable(active) else current_app.config.get("SITE")
    if site == "basal":
        return "/owner/coverage"
    return url_for("properties.index")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(_default_landing())

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or _default_landing())
        else:
            flash("Invalid email or password.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Registration page.

    Strecker is invite-gated during beta. A visitor without a valid
    unused code sees the register form with a code input and a
    "by invitation only" explanation; submitting without a valid code
    re-renders with an error. Basal stays open.
    """
    if current_user.is_authenticated:
        return redirect(_default_landing())

    # Invite code can arrive via query string (share-a-link flow) or
    # as a form field. Normalize whitespace + case so minor paste
    # artifacts ("  strek-..  ", uppercase) still match.
    invite_code_raw = (
        request.form.get("invite_code")
        or request.args.get("code")
        or ""
    ).strip().upper()

    require_invite = _require_invite()

    def _render(**extra):
        return render_template(
            "auth/register.html",
            require_invite=require_invite,
            invite_code=invite_code_raw,
            **extra,
        )

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()

        if not email or not password:
            flash("Email and password are required.", "error")
            return _render()

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return _render()

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("An account with that email already exists.", "error")
            return _render()

        invite = None
        if require_invite:
            if not invite_code_raw:
                flash(
                    "An invite code is required during beta. Paste yours below, "
                    "or email akira@strecker.app if you don't have one yet.",
                    "error",
                )
                return _render()
            invite = InviteCode.query.filter_by(
                code=invite_code_raw
            ).first()
            if not invite:
                flash("That invite code isn't valid.", "error")
                return _render()
            if invite.is_used:
                flash(
                    "That invite code has already been used. If this looks "
                    "wrong, email akira@strecker.app.",
                    "error",
                )
                return _render()

        user = User(email=email, display_name=display_name or None)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()   # populate user.id for the code linkage

        if invite is not None:
            invite.used_at = datetime.utcnow()
            invite.used_by_user_id = user.id

        db.session.commit()

        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return _render()


@auth_bp.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
