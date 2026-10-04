"""Read-only reviewer logins for Odoo and Langfuse, with the same credentials as Backhouse.

- Odoo: an internal user in "Show Accounting Features - Readonly" (can open bills, can't edit).
- Langfuse: a VIEWER in the Backhouse organisation (can open traces, can't change anything).

Odoo lets every user change their own password, so a visitor could lock other reviewers
out. This service re-applies the demo password every INTERVAL_SECONDS.
"""

from __future__ import annotations

import os
import sys
import time
import xmlrpc.client

import bcrypt
import psycopg

ODOO_URL = os.environ.get("ODOO_URL", "http://odoo:8069").rstrip("/")
ODOO_DB = os.environ.get("ODOO_DB", "odoo")
ODOO_ADMIN_LOGIN = os.environ.get("ODOO_ADMIN_LOGIN", "admin")
ODOO_ADMIN_PASSWORD = os.environ["ODOO_ADMIN_PASSWORD"]
DEMO_LOGIN = os.environ.get("DEMO_LOGIN", "reviewer@demo.backhouse")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")
LANGFUSE_DATABASE_URL = os.environ["LANGFUSE_DATABASE_URL"]
LANGFUSE_ORG_ID = os.environ.get("LANGFUSE_ORG_ID", "backhouse")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "900"))


def log(msg: str) -> None:
    print(f"[demo-accounts] {msg}", flush=True)


def ensure_odoo() -> None:
    uid = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common").authenticate(ODOO_DB, ODOO_ADMIN_LOGIN, ODOO_ADMIN_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo admin login failed")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)

    def call(model, method, *args, **kw):
        return models.execute_kw(ODOO_DB, uid, ODOO_ADMIN_PASSWORD, model, method, list(args), kw)

    groups = []
    for module, name in (("base", "group_user"), ("account", "group_account_readonly")):
        ref = call("ir.model.data", "search_read", [["module", "=", module], ["name", "=", name]], fields=["res_id"])
        if not ref:
            raise RuntimeError(f"Odoo group {module}.{name} not found (is the account module installed?)")
        groups.append(ref[0]["res_id"])
    vals = {"password": DEMO_PASSWORD, "groups_id": [(6, 0, groups)], "active": True}
    existing = call("res.users", "search", [["login", "=", DEMO_LOGIN]], context={"active_test": False})
    if existing:
        call("res.users", "write", existing, vals)
    else:
        call("res.users", "create", {"name": "Demo Reviewer", "login": DEMO_LOGIN, "email": DEMO_LOGIN, **vals})
        log(f"created Odoo user {DEMO_LOGIN} (read-only accounting)")


def ensure_langfuse() -> None:
    # Langfuse checks passwords with bcryptjs; same algorithm, "$2a$" prefix as Langfuse writes it.
    password_hash = bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt(12)).decode().replace("$2b$", "$2a$", 1)
    with psycopg.connect(LANGFUSE_DATABASE_URL) as conn:
        user_id = conn.execute(
            """
            INSERT INTO users (id, name, email, password, email_verified, created_at, updated_at)
            VALUES ('backhouse-demo-reviewer', 'Demo Reviewer', %s, %s, now(), now(), now())
            ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password, updated_at = now()
            RETURNING id
            """,
            (DEMO_LOGIN, password_hash),
        ).fetchone()[0]
        created = conn.execute(
            """
            INSERT INTO organization_memberships (id, org_id, user_id, role, created_at, updated_at)
            VALUES ('backhouse-demo-reviewer-membership', %s, %s, 'VIEWER', now(), now())
            ON CONFLICT (org_id, user_id) DO UPDATE SET role = 'VIEWER', updated_at = now()
            RETURNING (xmax = 0)
            """,
            (LANGFUSE_ORG_ID, user_id),
        ).fetchone()[0]
        if created:
            log(f"created Langfuse viewer {DEMO_LOGIN}")


def main() -> None:
    once = "--once" in sys.argv
    ok_logged = False
    while True:
        try:
            ensure_odoo()
            ensure_langfuse()
            if not ok_logged:
                log(f"reviewer logins ready; demo password re-applied every {INTERVAL // 60} min")
                ok_logged = True
            if once:
                return
            time.sleep(INTERVAL)
        except Exception as exc:  # services still starting, migrations not run yet, ...
            log(f"not ready yet: {type(exc).__name__}: {exc}"[:300])
            if once:
                sys.exit(1)
            time.sleep(30)


if __name__ == "__main__":
    main()
