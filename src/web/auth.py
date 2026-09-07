"""
auth.py
========
Role-Based Access Control (RBAC) and session authentication for the Flask dashboard.
Enforces two primary organisational roles:
  1. DATABASE / PLATFORM ADMIN (dba_admin)
  2. APPLICATION / ENGINEERING REVIEWER (release_engineer)

Security principles:
- Server-side session verification: Roles are strictly extracted from session state.
- Request payload role escalation is prohibited.
- Unauthenticated requests return HTTP 401.
- Unauthorized actions return HTTP 403.
- Uses synthetic test users only (Zero real PII).
"""

import os
from functools import wraps
from typing import Optional, Dict, Any, List
from flask import session, redirect, url_for, flash, jsonify, request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")

# Environment-based Synthetic Demo Credentials (Development Fallback Only)
# In production, credentials must be managed via an enterprise Identity Provider (OIDC/SAML).
# Application source code must not contain hard-coded production secrets.

def get_demo_credentials() -> Dict[str, str]:
    """
    Retrieves demo credentials from environment variables with synthetic development fallbacks.
    Environment variables:
      - DEMO_DBA_PASSWORD: Password for dba_admin and admin_user
      - DEMO_REVIEWER_PASSWORD: Password for release_eng and reviewer_user
    """
    dba_pw = os.environ.get("DEMO_DBA_PASSWORD", "admin@123")
    rev_pw = os.environ.get("DEMO_REVIEWER_PASSWORD", "admin@123")
    return {
        "dba_password": dba_pw,
        "reviewer_password": rev_pw
    }


def get_demo_users() -> Dict[str, Dict[str, Any]]:
    """Constructs synthetic user registry dynamically from environment-configured credentials."""
    creds = get_demo_credentials()
    return {
        "dba_admin": {
            "user_id": "USR-DBA-01",
            "password": creds["dba_password"],
            "role": "dba_admin",
            "display_name": "DBA / Platform Administrator",
        },
        "admin_user": {
            "user_id": "USR-DBA-02",
            "password": creds["dba_password"],
            "role": "dba_admin",
            "display_name": "Database Platform Admin",
        },
        "release_eng": {
            "user_id": "USR-REV-01",
            "password": creds["reviewer_password"],
            "role": "release_engineer",
            "display_name": "Application / Engineering Reviewer",
        },
        "reviewer_user": {
            "user_id": "USR-REV-02",
            "password": creds["reviewer_password"],
            "role": "release_engineer",
            "display_name": "Engineering Reviewer",
        },
    }


# Dynamic USERS mapping for backward compatibility
USERS = get_demo_users()

# Role synonyms for flexible role checking
ROLE_ALIASES = {
    "database_platform_admin": "dba_admin",
    "dba_admin": "dba_admin",
    "dba": "dba_admin",
    "platform_admin": "dba_admin",
    "application_engineering_reviewer": "release_engineer",
    "release_engineer": "release_engineer",
    "reviewer": "release_engineer",
    "engineering_reviewer": "release_engineer",
}


def normalize_role(role: Optional[str]) -> str:
    """Normalizes role strings to canonical 'dba_admin' or 'release_engineer'."""
    if not role:
        return ""
    clean = str(role).strip().lower().replace(" ", "_").replace("/", "_")
    return ROLE_ALIASES.get(clean, clean)


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Return user dict if credentials valid against environment-supplied passwords, else None."""
    users = get_demo_users()
    user = users.get(username)
    if user and user["password"] == password:
        return user
    return None


def login_required(f):
    """HTML route decorator requiring authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def dba_required(f):
    """HTML route decorator requiring dba_admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        user_role = normalize_role(session.get("role"))
        if user_role != "dba_admin":
            flash("Access denied: This action requires DBA Administrator role.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def login_required_api(f):
    """API decorator returning HTTP 401 if unauthenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return jsonify({
                "status": "error",
                "error": "Unauthorized",
                "message": "Authentication required. Active session required."
            }), 401
        return f(*args, **kwargs)
    return decorated


def role_required_api(allowed_roles: List[str]):
    """API decorator enforcing that the session role is in allowed_roles."""
    norm_allowed = [normalize_role(r) for r in allowed_roles]

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "username" not in session:
                return jsonify({
                    "status": "error",
                    "error": "Unauthorized",
                    "message": "Authentication required. Please log in."
                }), 401

            session_role = normalize_role(session.get("role"))
            if session_role not in norm_allowed:
                return jsonify({
                    "status": "error",
                    "error": "Forbidden",
                    "message": f"Access denied: Role '{session.get('role')}' lacks permission for this resource."
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def dba_required_api(f):
    """API decorator strictly requiring dba_admin session role."""
    return role_required_api(["dba_admin"])(f)


def current_user() -> Dict[str, str]:
    """Returns active session user attributes."""
    return {
        "user_id": session.get("user_id", "ANON"),
        "username": session.get("username", ""),
        "role": session.get("role", ""),
        "display_name": session.get("display_name", "Guest"),
    }


def can(capability: str) -> bool:
    """Check if current session user has a capability from rules.yaml."""
    from src.core.rules_loader import load_rules, get_role_caps
    try:
        rules = load_rules(RULES_PATH)
        role = normalize_role(session.get("role", ""))
        caps = get_role_caps(rules, role)
        return caps.get(capability, False)
    except Exception:
        return False
