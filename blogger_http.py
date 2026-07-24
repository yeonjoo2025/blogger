"""Shared HTTP helpers that tolerate corporate SSL interception."""

from __future__ import annotations

import urllib3
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
import httplib2
import requests

from blogger_auth import load_credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_orig_request = requests.Session.request


def _insecure_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("verify", False)
    return _orig_request(self, method, url, **kwargs)


# Patch once for google.auth.transport.requests token refresh.
requests.Session.request = _insecure_request  # type: ignore[method-assign]


def build_blogger_service():
    creds = load_credentials()
    http = AuthorizedHttp(
        creds,
        http=httplib2.Http(disable_ssl_certificate_validation=True),
    )
    return build("blogger", "v3", http=http, cache_discovery=False)


def authed_get(url: str, params: dict | None = None) -> requests.Response:
    creds = load_credentials()
    if not creds.valid:
        raise SystemExit("Invalid Blogger credentials")
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        params=params or {},
        timeout=30,
        verify=False,
    )
