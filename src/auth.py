"""OAuth helpers for Google Classroom + Drive backup.

First run: starts a local HTTP server on localhost:8080, prints the consent
URL, and waits for the redirect. The resulting token (with refresh token) is
saved to TOKEN_PATH so subsequent runs are non-interactive.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def _prefer_ipv4() -> None:
    """Prefer IPv4 when resolving hostnames.

    googleapiclient uses httplib2, which can hang indefinitely on broken IPv6
    routes because it has no default timeout and does not fall back to IPv4
    as quickly as curl or requests.
    """
    if getattr(_prefer_ipv4, "_patched", False):
        return

    orig_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if family in (0, socket.AF_UNSPEC, socket.AF_INET):
            v4 = orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            if v4:
                return v4
        return orig_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    _prefer_ipv4._patched = True


_prefer_ipv4()

BASE_DIR = Path(__file__).resolve().parent.parent
CLIENT_SECRETS = BASE_DIR / "google_oauth_tokens.json"
TOKEN_PATH = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.topics.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _select_port(preferred_port: int = 8080) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred_port))
            return preferred_port
        except OSError:
            return 0


def load_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(creds)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(
        port=_select_port(),
        host="localhost",
        access_type="offline",
        prompt="consent",
        open_browser=False,
    )
    _save(creds)
    return creds


def _save(creds: Credentials) -> None:
    TOKEN_PATH.write_text(creds.to_json())


def build_service(
    api: str,
    version: str,
    creds: Credentials,
    *,
    timeout: int = 120,
) -> Any:
    """Build a Google API client with IPv4 preference and HTTP timeouts."""
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=timeout))
    return build(api, version, http=http, cache_discovery=False)
