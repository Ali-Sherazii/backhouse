#!/bin/sh
# Imports and activates the Backhouse workflows on first boot, then starts n8n.
# To re-import after editing the JSON: delete the marker in the n8n-data volume
#   docker compose exec n8n rm /home/node/.n8n/.backhouse-workflows-v1 && docker compose restart n8n
set -e

DATA=/home/node/.n8n
MARK="$DATA/.backhouse-workflows-v1"

if [ ! -f "$MARK" ]; then
  echo "[backhouse] importing workflows"
  n8n import:workflow --separate --input=/opt/backhouse/workflows
  n8n update:workflow --id=bhExportOdoo0001 --active=true
  n8n update:workflow --id=bhIntakeMailpit1 --active=true
  touch "$MARK"
fi

# Optional real inbox: only when IMAP credentials are configured.
if [ -n "$IMAP_HOST" ] && [ ! -f "$DATA/.backhouse-imap-v1" ]; then
  echo "[backhouse] importing IMAP credential for $IMAP_USER"
  node -e '
    const e = process.env;
    console.log(JSON.stringify([{
      id: "bhImapCredent001", name: "Backhouse IMAP", type: "imap",
      data: { user: e.IMAP_USER, password: e.IMAP_PASSWORD, host: e.IMAP_HOST,
              port: Number(e.IMAP_PORT || 993), secure: true, allowUnauthorizedCerts: false }
    }]));' > /tmp/imap-credential.json
  n8n import:credentials --input=/tmp/imap-credential.json
  rm -f /tmp/imap-credential.json
  n8n update:workflow --id=bhIntakeImap0001 --active=true
  touch "$DATA/.backhouse-imap-v1"
fi

exec n8n start
