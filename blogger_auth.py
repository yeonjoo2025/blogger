"""Shared Blogger OAuth helpers for local + Cloud Agent runs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")
CLIENT_SECRET_PATH = Path("client_secret.json")

# Cloud Agent Secrets tab → Runtime Secret / Environment Variable
TOKEN_ENV_KEYS = ("BLOGGER_TOKEN_JSON", "BLOGGER_TOKEN", "TOKEN_JSON")
CLIENT_SECRET_ENV_KEYS = (
    "BLOGGER_CLIENT_SECRET_JSON",
    "BLOGGER_CLIENT_SECRET",
    "CLIENT_SECRET_JSON",
)


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def ensure_token_file() -> Path:
    """Ensure token.json exists, creating it from env secrets when needed."""
    if TOKEN_PATH.exists():
        return TOKEN_PATH

    raw = _first_env(*TOKEN_ENV_KEYS)
    if not raw:
        raise SystemExit(
            "token.json not found and no BLOGGER_TOKEN_JSON/TOKEN_JSON env secret.\n"
            "Local: python get_token.py\n"
            "Cloud: Dashboard → Cloud Agents → Secrets (Personal)에 "
            "BLOGGER_TOKEN_JSON = token.json 전체 내용 등록"
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "BLOGGER_TOKEN_JSON/TOKEN_JSON is not valid JSON. "
            "Paste the full contents of token.json."
        ) from exc

    TOKEN_PATH.write_text(json.dumps(data), encoding="utf-8")
    return TOKEN_PATH


def ensure_client_secret_file() -> Path:
    """Ensure client_secret.json exists for local OAuth flows."""
    if CLIENT_SECRET_PATH.exists():
        return CLIENT_SECRET_PATH

    candidates = sorted(Path(".").glob("client_secret_*.apps.googleusercontent.com.json"))
    if candidates:
        return candidates[0]

    raw = _first_env(*CLIENT_SECRET_ENV_KEYS)
    if not raw:
        raise SystemExit(
            "Missing client_secret*.json and no BLOGGER_CLIENT_SECRET_JSON env secret."
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "BLOGGER_CLIENT_SECRET_JSON is not valid JSON."
        ) from exc

    CLIENT_SECRET_PATH.write_text(json.dumps(data), encoding="utf-8")
    return CLIENT_SECRET_PATH


def load_credentials() -> Credentials:
    ensure_token_file()
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            raise SystemExit(
                "AUTH_REFRESH_FAILED: Blogger OAuth refresh_token expired/revoked. "
                "Local: python get_token.py then update Cloud Agent secret "
                "BLOGGER_TOKEN (or BLOGGER_TOKEN_JSON) with the new token.json. "
                f"detail={exc}"
            ) from exc
    if not creds.valid:
        raise SystemExit(
            "AUTH_INVALID: Token invalid. Re-run: python get_token.py and update "
            "BLOGGER_TOKEN / BLOGGER_TOKEN_JSON secret."
        )
    return creds
