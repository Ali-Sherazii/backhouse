"""Write a ready-to-use .env with fresh random secrets.

    python3 infra/generate_env.py --domain backhouse.example.com > .env   # a server
    python3 infra/generate_env.py --local > .env                         # this machine

Starts from .env.example, replaces every change-me value with a random secret, and fills
the domain-dependent values: the four hostnames, their public URLs and the email-intake
address. Review the result (HF_TOKEN, LLM settings, SLACK_WEBHOOK_URL) before starting.
"""

from __future__ import annotations

import argparse
import re
import secrets
import string
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def password(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    # Always contains an uppercase letter and a digit (n8n's password rule).
    return "Bh" + "".join(secrets.choice(alphabet) for _ in range(n)) + "7"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--domain", help="hostname of the app, e.g. backhouse.example.com; tools go on n8n./odoo./traces. under it")
    target.add_argument("--local", action="store_true", help="localhost URLs, no public SMTP")
    args = ap.parse_args()

    if args.local:
        values = {
            "APP_DOMAIN": "backhouse.localhost",
            "N8N_DOMAIN": "n8n.backhouse.localhost",
            "ODOO_DOMAIN": "odoo.backhouse.localhost",
            "TRACES_DOMAIN": "traces.backhouse.localhost",
            "APP_PUBLIC_URL": "http://localhost:3000",
            "ODOO_PUBLIC_URL": "http://localhost:8069",
            "LANGFUSE_PUBLIC_URL": "http://localhost:3001",
            "N8N_PUBLIC_URL": "http://localhost:5678",
            "INTAKE_EMAIL": "",
            "SMTP_PUBLIC_BIND": "127.0.0.1",
            "N8N_SECURE_COOKIE": "false",
        }
    else:
        d = args.domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        values = {
            "APP_DOMAIN": d,
            "N8N_DOMAIN": f"n8n.{d}",
            "ODOO_DOMAIN": f"odoo.{d}",
            "TRACES_DOMAIN": f"traces.{d}",
            "APP_PUBLIC_URL": f"https://{d}",
            "ODOO_PUBLIC_URL": f"https://odoo.{d}",
            "LANGFUSE_PUBLIC_URL": f"https://traces.{d}",
            "N8N_PUBLIC_URL": f"https://n8n.{d}",
            "INTAKE_EMAIL": f"invoices@{d}",
            "SMTP_PUBLIC_BIND": "0.0.0.0",
            "N8N_SECURE_COOKIE": "true",
        }
    values.update(
        {
            "LANGFUSE_ENCRYPTION_KEY": secrets.token_hex(32),
            "LANGFUSE_PUBLIC_KEY": "pk-lf-" + secrets.token_hex(8),
            "LANGFUSE_SECRET_KEY": "sk-lf-" + secrets.token_hex(16),
            "N8N_OWNER_PASSWORD": password(),
            "LANGFUSE_INIT_USER_PASSWORD": password(),
            "ODOO_ADMIN_PASSWORD": password(),
        }
    )

    out = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if m:
            key, value = m.groups()
            if key in values:
                value = values[key]
            elif "change-me" in value.lower():
                value = secrets.token_hex(20)
            line = f"{key}={value}"
        out.append(line)
    text = "\n".join(out) + "\n"
    if "change-me" in text.lower():
        sys.exit("a change-me value was left unreplaced")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
