"""One-shot Odoo setup over XML-RPC. Safe to run again.

- rotates the default admin/admin password to ODOO_ADMIN_PASSWORD
- renames the main company to "Demo Bistro" (US, USD)
- installs the `account` module (Invoicing)
- creates the demo vendors as supplier partners
- stores each partner id in backhouse's vendors.odoo_partner_id

Runs automatically as the `odoo-seed` compose service, or by hand:
    docker compose run --rm odoo-seed
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, "/app")  # backend package inside the image

ODOO_URL = os.environ.get("ODOO_URL", "http://odoo:8069").rstrip("/")
DB = os.environ.get("ODOO_DB", "odoo")
LOGIN = os.environ.get("ODOO_ADMIN_LOGIN", "admin")
PASSWORD = os.environ["ODOO_ADMIN_PASSWORD"]
SAMPLES = Path(os.environ.get("SAMPLES_DIR", "/samples"))


def log(msg: str) -> None:
    print(f"[odoo-seed] {msg}", flush=True)


def wait_for_odoo(timeout: int = 600) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{ODOO_URL}/web/health", timeout=5) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(5)
    raise SystemExit("Odoo did not become healthy in time")


def connect() -> tuple[int, str, xmlrpc.client.ServerProxy]:
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
    uid = common.authenticate(DB, LOGIN, PASSWORD, {})
    if uid:
        return uid, PASSWORD, models
    # Fresh database: Odoo's default admin password is "admin". Rotate it.
    uid = common.authenticate(DB, LOGIN, "admin", {})
    if not uid:
        raise SystemExit("Can't log in to Odoo with ODOO_ADMIN_PASSWORD or the default password")
    models.execute_kw(DB, uid, "admin", "res.users", "write", [[uid], {"password": PASSWORD}])
    log("rotated default admin password")
    return common.authenticate(DB, LOGIN, PASSWORD, {}), PASSWORD, models


def main() -> None:
    wait_for_odoo()
    uid, pw, models = connect()

    def call(model, method, *args, **kw):
        return models.execute_kw(DB, uid, pw, model, method, list(args), kw)

    us = call("res.country", "search", [["code", "=", "US"]], limit=1)
    usd = call("res.currency", "search", [["name", "=", "USD"]], limit=1)
    company_vals = {"name": "Demo Bistro", "street": "14 Harbour Street", "city": "Portland", "zip": "04101"}
    if us:
        company_vals["country_id"] = us[0]
    if usd:
        company_vals["currency_id"] = usd[0]
    current = call("res.company", "read", [1], fields=list(company_vals))[0]
    # Only write what differs: Odoo refuses a currency write once journal entries exist.
    changes = {
        k: v
        for k, v in company_vals.items()
        if (current[k][0] if isinstance(current[k], list) else current[k]) != v
    }
    if changes:
        call("res.company", "write", [1], changes)
    log("company set to Demo Bistro")

    mod = call("ir.module.module", "search_read", [["name", "=", "account"]], fields=["state"])
    if mod and mod[0]["state"] != "installed":
        log("installing account module (takes a minute or two)...")
        call("ir.module.module", "button_immediate_install", [mod[0]["id"]])
        log("account installed")
    else:
        log("account already installed")

    vendors = json.loads((SAMPLES / "vendors.json").read_text(encoding="utf-8"))
    partner_ids: dict[str, int] = {}
    for v in vendors:
        found = call("res.partner", "search", [["name", "=", v["name"]], ["is_company", "=", True]], limit=1)
        if found:
            pid = found[0]
        else:
            pid = call(
                "res.partner",
                "create",
                {"name": v["name"], "is_company": True, "supplier_rank": 1, "vat": v["tax_id"], "country_id": us[0] if us else False},
            )
            log(f"created partner {v['name']} ({pid})")
        partner_ids[v["name"]] = pid

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Vendor

    db = SessionLocal()
    try:
        for vendor in db.scalars(select(Vendor)).all():
            if vendor.name in partner_ids and vendor.odoo_partner_id != partner_ids[vendor.name]:
                vendor.odoo_partner_id = partner_ids[vendor.name]
        db.commit()
    finally:
        db.close()
    log(f"linked {len(partner_ids)} vendors to Odoo partners. Done.")


if __name__ == "__main__":
    main()
