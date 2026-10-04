"""One-shot: create the n8n owner account from .env before n8n is reachable publicly.

A fresh n8n hands its owner account to whoever calls /rest/owner/setup first, so this
runs before Caddy starts. Safe to run again: once an owner exists it does nothing.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

N8N_URL = os.environ.get("N8N_URL", "http://n8n:5678").rstrip("/")
EMAIL = os.environ.get("N8N_OWNER_EMAIL", "")
PASSWORD = os.environ.get("N8N_OWNER_PASSWORD", "")


def log(msg: str) -> None:
    print(f"[n8n-owner] {msg}", flush=True)


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{N8N_URL}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, ValueError, OSError):
        return 0, None


def main() -> None:
    if not EMAIL or not PASSWORD:
        sys.exit("N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD must be set")
    deadline = time.time() + 600
    while time.time() < deadline:
        # n8n answers its health check before the REST routes are registered, so poll settings.
        status, body = request("GET", "/rest/settings")
        if status == 200 and body:
            setup_pending = body.get("data", {}).get("userManagement", {}).get("showSetupOnFirstLoad")
            if setup_pending is False:
                log("owner already exists, nothing to do")
                return
            status, body = request(
                "POST",
                "/rest/owner/setup",
                {"email": EMAIL, "firstName": "Backhouse", "lastName": "Admin", "password": PASSWORD},
            )
            if status == 200:
                log(f"created owner {EMAIL}")
                return
            log(f"setup returned {status}: {body}")
        time.sleep(3)
    sys.exit("n8n did not become ready in time")


if __name__ == "__main__":
    main()
