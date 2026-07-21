"""Shared Blogger OAuth helpers."""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")


def load_credentials() -> Credentials:
    if not TOKEN_PATH.exists():
        raise SystemExit("token.json not found. Provide BLOGGER_TOKEN or run get_token.py")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise SystemExit("Token invalid. Re-issue BLOGGER_TOKEN / run get_token.py")
    return creds
