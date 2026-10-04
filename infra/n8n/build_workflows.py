"""Builds the n8n workflow JSON files in infra/n8n/workflows/.

    python infra/n8n/build_workflows.py

The JSON files are what n8n imports on first boot (see entrypoint.sh). This script only
exists so the workflows stay readable and diffable; editing them in the n8n UI and
exporting with `n8n export:workflow --id=... --output=...` works too.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent / "workflows"
NS = uuid.UUID("6f1d3c52-8d0e-4b4e-9d58-0f6c7e1d2a10")

EXPORT_ID = "bhExportOdoo0001"
INTAKE_ID = "bhIntakeMailpit1"
IMAP_ID = "bhIntakeImap0001"
IMAP_CRED_ID = "bhImapCredent001"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def node(wf: str, name: str, type_: str, version: float, params: dict, pos: tuple[int, int], **extra) -> dict:
    return {
        "parameters": params,
        "id": uid(wf, name),
        "name": name,
        "type": type_,
        "typeVersion": version,
        "position": list(pos),
        **extra,
    }


def link(*targets: str) -> list[dict]:
    return [{"node": t, "type": "main", "index": 0} for t in targets]


def http_json(url: str, body_expr: str, *, method: str = "POST", secret: bool = False) -> dict:
    p = {
        "method": method,
        "url": url,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": body_expr,
        "options": {},
    }
    if secret:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": "X-Backhouse-Secret", "value": "={{ $env.WEBHOOK_SECRET }}"}]}
    return p


def if_node(wf: str, name: str, left: str, operator: dict, pos, right: str = "") -> dict:
    return node(
        wf, name, "n8n-nodes-base.if", 2,
        {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                "conditions": [{"id": uid(wf, name, "cond"), "leftValue": left, "rightValue": right, "operator": operator}],
                "combinator": "and",
            },
            "options": {},
        },
        pos,
    )


def code(wf: str, name: str, js: str, pos, each_item: bool = False) -> dict:
    params = {"jsCode": js.strip()}
    if each_item:
        params["mode"] = "runOnceForEachItem"
    return node(wf, name, "n8n-nodes-base.code", 2, params, pos)


def odoo_call(model: str, method: str, args_js: str, kwargs_js: str = "{}") -> str:
    """JSON-RPC body for Odoo execute_kw; uid comes from the login node."""
    return (
        "={{ JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { service: 'object', method: 'execute_kw', "
        f"args: [$env.ODOO_DB, $('Odoo login').first().json.result, $env.ODOO_PASSWORD, '{model}', '{method}', {args_js}, {kwargs_js}] }} }}) }}}}"
    )


def workflow(id_: str, name: str, nodes: list[dict], connections: dict) -> dict:
    return {
        "id": id_,
        "name": name,
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "saveManualExecutions": True},
        "pinData": {},
        "tags": [],
        "versionId": uid(id_, "version"),
    }


# --- Export: approved invoice -> Odoo vendor bill -> report back -> alerts ----------------

ODOO = "={{ $env.ODOO_URL }}/jsonrpc"
BODY = "$('Webhook').first().json.body"


def export_workflow() -> dict:
    wf = EXPORT_ID
    nodes = [
        node(wf, "Webhook", "n8n-nodes-base.webhook", 2,
             {"httpMethod": "POST", "path": "backhouse-export", "responseMode": "onReceived", "options": {}},
             (0, 300), webhookId=uid(wf, "webhook")),
        if_node(wf, "Secret OK?", "={{ $json.headers['x-backhouse-secret'] }}",
                {"type": "string", "operation": "equals"}, (220, 300), right="={{ $env.WEBHOOK_SECRET }}"),
        node(wf, "Odoo login", "n8n-nodes-base.httpRequest", 4.2, http_json(
            ODOO,
            "={{ JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { service: 'common', method: 'login', "
            "args: [$env.ODOO_DB, $env.ODOO_LOGIN, $env.ODOO_PASSWORD] } }) }}",
        ), (440, 280)),
        node(wf, "Find partner", "n8n-nodes-base.httpRequest", 4.2, http_json(
            ODOO,
            odoo_call(
                "res.partner", "search_read",
                f"[{BODY}.vendor.odoo_partner_id ? [['id', '=', {BODY}.vendor.odoo_partner_id]] : [['name', '=ilike', {BODY}.vendor.name], ['is_company', '=', true]]]",
                "{ fields: ['id', 'name'], limit: 1 }",
            ),
        ), (660, 280)),
        if_node(wf, "Partner exists?", "={{ ($json.result || []).length > 0 }}",
                {"type": "boolean", "operation": "true", "singleValue": True}, (880, 280)),
        code(wf, "Use existing partner", "return [{ json: { partner_id: $input.first().json.result[0].id } }];", (1100, 180)),
        node(wf, "Create partner", "n8n-nodes-base.httpRequest", 4.2, http_json(
            ODOO,
            odoo_call(
                "res.partner", "create",
                f"[{{ name: {BODY}.vendor.name, is_company: true, supplier_rank: 1, vat: {BODY}.vendor.tax_id || false }}]",
            ),
        ), (1100, 380)),
        code(wf, "Use new partner", """
const r = $input.first().json;
if (r.error) throw new Error('Odoo: ' + JSON.stringify(r.error.data?.message || r.error.message));
return [{ json: { partner_id: r.result } }];
""", (1320, 380)),
        code(wf, "Build bill", """
const p = $('Webhook').first().json.body;
const inv = p.invoice;
const lines = (inv.lines || []).map(l => [0, 0, {
  name: l.description || 'Item',
  quantity: l.quantity ?? 1,
  price_unit: l.unit_price ?? l.amount ?? 0,
  tax_ids: [[6, 0, []]],
}]);
if (inv.discount) {
  lines.push([0, 0, { name: 'Discount (as invoiced)', quantity: 1, price_unit: -Math.abs(inv.discount), tax_ids: [[6, 0, []]] }]);
}
if (inv.tax) {
  lines.push([0, 0, { name: 'Sales tax (as invoiced)', quantity: 1, price_unit: inv.tax, tax_ids: [[6, 0, []]] }]);
}
const vals = {
  move_type: 'in_invoice',
  partner_id: $json.partner_id,
  ref: inv.number,
  invoice_date: inv.date,
  narration: `Imported by Backhouse from document #${p.document_id}: ${p.document_url}`,
  invoice_line_ids: lines,
};
if (inv.due_date) vals.invoice_date_due = inv.due_date;
return [{ json: { partner_id: $json.partner_id, vals } }];
""", (1540, 280)),
        node(wf, "Create bill", "n8n-nodes-base.httpRequest", 4.2, http_json(
            ODOO, odoo_call("account.move", "create", "[$json.vals]"),
        ), (1760, 280)),
        code(wf, "Check Odoo result", """
const r = $input.first().json;
if (r.error) throw new Error('Odoo: ' + JSON.stringify(r.error.data?.message || r.error.message));
return [{ json: { odoo_bill_id: r.result, odoo_partner_id: $('Build bill').first().json.partner_id } }];
""", (1980, 280)),
        node(wf, "Report to Backhouse", "n8n-nodes-base.httpRequest", 4.2, http_json(
            "={{ $env.BACKHOUSE_API_URL }}/webhooks/exported",
            "={{ JSON.stringify({ document_id: $('Webhook').first().json.body.document_id, "
            "odoo_bill_id: $json.odoo_bill_id, odoo_partner_id: $json.odoo_partner_id }) }}",
            secret=True,
        ), (2200, 280)),
        if_node(wf, "Alert needed?", f"={{{{ {BODY}.alert }}}}",
                {"type": "boolean", "operation": "true", "singleValue": True}, (2420, 280)),
        code(wf, "Compose alert", """
const p = $('Webhook').first().json.body;
const bill = $('Check Odoo result').first().json.odoo_bill_id;
const head = `Invoice ${p.invoice.number} from ${p.vendor.name} (${p.invoice.currency || ''} ${p.invoice.total}) was approved by ${p.approved_by} and sent to Odoo as bill #${bill}.`;
const lines = [head, ''];
if (p.guard_flagged) lines.push('- The injection guard flagged this document before it was approved. Check it was intended.');
for (const w of p.warnings || []) lines.push(`- ${w.check === 'price_change' ? 'Price change' : w.check}: ${w.detail}`);
lines.push('', `Open in Backhouse: ${p.document_url}`);
const subject = p.guard_flagged
  ? `[Backhouse] Flagged invoice approved: ${p.vendor.name} ${p.invoice.number}`
  : `[Backhouse] Price change: ${p.vendor.name} ${p.invoice.number}`;
return [{ json: { subject, text: lines.join('\\n') } }];
""", (2640, 200)),
        if_node(wf, "Slack configured?", "={{ $env.SLACK_WEBHOOK_URL }}",
                {"type": "string", "operation": "notEmpty", "singleValue": True}, (2860, 200)),
        node(wf, "Slack alert", "n8n-nodes-base.httpRequest", 4.2, http_json(
            "={{ $env.SLACK_WEBHOOK_URL }}", "={{ JSON.stringify({ text: '*' + $json.subject + '*\\n' + $json.text }) }}",
        ), (3080, 100)),
        node(wf, "Email alert (Mailpit)", "n8n-nodes-base.httpRequest", 4.2, http_json(
            "={{ $env.MAILPIT_URL }}/api/v1/send",
            "={{ JSON.stringify({ From: { Email: 'alerts@demo.backhouse', Name: 'Backhouse' }, "
            "To: [{ Email: $env.ALERT_EMAIL_TO }], Subject: $json.subject, Text: $json.text }) }}",
        ), (3080, 300)),
    ]
    connections = {
        "Webhook": {"main": [link("Secret OK?")]},
        "Secret OK?": {"main": [link("Odoo login"), []]},
        "Odoo login": {"main": [link("Find partner")]},
        "Find partner": {"main": [link("Partner exists?")]},
        "Partner exists?": {"main": [link("Use existing partner"), link("Create partner")]},
        "Use existing partner": {"main": [link("Build bill")]},
        "Create partner": {"main": [link("Use new partner")]},
        "Use new partner": {"main": [link("Build bill")]},
        "Build bill": {"main": [link("Create bill")]},
        "Create bill": {"main": [link("Check Odoo result")]},
        "Check Odoo result": {"main": [link("Report to Backhouse")]},
        "Report to Backhouse": {"main": [link("Alert needed?")]},
        "Alert needed?": {"main": [link("Compose alert"), []]},
        "Compose alert": {"main": [link("Slack configured?")]},
        "Slack configured?": {"main": [link("Slack alert"), link("Email alert (Mailpit)")]},
    }
    return workflow(EXPORT_ID, "Backhouse: export approved invoice to Odoo", nodes, connections)


# --- Intake: Mailpit inbox (local demo) -----------------------------------------------------

ATTACHMENT_FILTER = r"/\.(pdf|png|jpe?g|webp|tiff?)$/i.test(name) || /^(application\/pdf|image\/)/.test(type)"


def upload_node(wf: str, pos, sender_expr: str, subject_expr: str) -> dict:
    return node(wf, "Send to Backhouse", "n8n-nodes-base.httpRequest", 4.2, {
        "method": "POST",
        "url": "={{ $env.BACKHOUSE_API_URL }}/webhooks/intake",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "X-Backhouse-Secret", "value": "={{ $env.WEBHOOK_SECRET }}"}]},
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data"},
            {"name": "sender", "value": sender_expr},
            {"name": "subject", "value": subject_expr},
        ]},
        "options": {},
    }, pos)


def intake_mailpit_workflow() -> dict:
    wf = INTAKE_ID
    meta = "$('One item per attachment').item.json"
    nodes = [
        node(wf, "Every 20 seconds", "n8n-nodes-base.scheduleTrigger", 1.2,
             {"rule": {"interval": [{"field": "seconds", "secondsInterval": 20}]}}, (0, 300)),
        node(wf, "Unread mail", "n8n-nodes-base.httpRequest", 4.2,
             {"method": "GET", "url": "={{ $env.MAILPIT_URL }}/api/v1/search?query=is%3Aunread&limit=25", "options": {}},
             (220, 300)),
        code(wf, "One item per message", """
const msgs = $input.first().json.messages || [];
return msgs.map(m => ({ json: { id: m.ID, from: m.From?.Address || '', subject: m.Subject || '' } }));
""", (440, 300)),
        node(wf, "Mark read", "n8n-nodes-base.httpRequest", 4.2, http_json(
            "={{ $env.MAILPIT_URL }}/api/v1/messages", "={{ JSON.stringify({ IDs: [$json.id], Read: true }) }}", method="PUT",
        ), (660, 460)),
        node(wf, "Message detail", "n8n-nodes-base.httpRequest", 4.2,
             {"method": "GET", "url": "={{ $env.MAILPIT_URL }}/api/v1/message/{{ $json.id }}", "options": {}}, (660, 300)),
        code(wf, "One item per attachment", f"""
const out = [];
for (const item of $input.all()) {{
  const m = item.json;
  for (const a of m.Attachments || []) {{
    const name = a.FileName || '';
    const type = a.ContentType || '';
    if ({ATTACHMENT_FILTER}) {{
      out.push({{ json: {{ message_id: m.ID, part_id: a.PartID, filename: name, content_type: type,
        from: m.From?.Address || '', subject: m.Subject || '' }} }});
    }}
  }}
}}
return out;
""", (880, 300)),
        node(wf, "Download attachment", "n8n-nodes-base.httpRequest", 4.2, {
            "method": "GET",
            "url": "={{ $env.MAILPIT_URL }}/api/v1/message/{{ $json.message_id }}/part/{{ $json.part_id }}",
            "options": {"response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}},
        }, (1100, 300)),
        code(wf, "Set file name", f"""
const meta = {meta};
const item = $input.item;
item.binary.data.fileName = meta.filename;
if (meta.content_type) item.binary.data.mimeType = meta.content_type;
item.json = meta;
return item;
""", (1320, 300), each_item=True),
        upload_node(wf, (1540, 300), "={{ $json.from }}", "={{ $json.subject }}"),
    ]
    connections = {
        "Every 20 seconds": {"main": [link("Unread mail")]},
        "Unread mail": {"main": [link("One item per message")]},
        "One item per message": {"main": [link("Message detail", "Mark read")]},
        "Message detail": {"main": [link("One item per attachment")]},
        "One item per attachment": {"main": [link("Download attachment")]},
        "Download attachment": {"main": [link("Set file name")]},
        "Set file name": {"main": [link("Send to Backhouse")]},
    }
    return workflow(INTAKE_ID, "Backhouse: email intake (Mailpit)", nodes, connections)


# --- Intake: real IMAP inbox (Gmail etc.), activated when IMAP_HOST is set ------------------


def intake_imap_workflow() -> dict:
    wf = IMAP_ID
    nodes = [
        node(wf, "Email Trigger (IMAP)", "n8n-nodes-base.emailReadImap", 2, {
            "mailbox": "INBOX",
            "postProcessAction": "read",
            "downloadAttachments": True,
            "options": {"customEmailConfig": "[\"UNSEEN\"]"},
        }, (0, 300), credentials={"imap": {"id": IMAP_CRED_ID, "name": "Backhouse IMAP"}}),
        code(wf, "One item per attachment", f"""
const out = [];
for (const item of $input.all()) {{
  for (const bin of Object.values(item.binary || {{}})) {{
    const name = bin.fileName || '';
    const type = bin.mimeType || '';
    if ({ATTACHMENT_FILTER}) {{
      out.push({{ json: {{ from: item.json.from || '', subject: item.json.subject || '', filename: name }}, binary: {{ data: bin }} }});
    }}
  }}
}}
return out;
""", (220, 300)),
        upload_node(wf, (440, 300), "={{ $json.from }}", "={{ $json.subject }}"),
    ]
    connections = {
        "Email Trigger (IMAP)": {"main": [link("One item per attachment")]},
        "One item per attachment": {"main": [link("Send to Backhouse")]},
    }
    return workflow(IMAP_ID, "Backhouse: email intake (IMAP inbox)", nodes, connections)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for fname, wf in (
        ("export.json", export_workflow()),
        ("intake.json", intake_mailpit_workflow()),
        ("intake-imap.json", intake_imap_workflow()),
    ):
        (OUT / fname).write_text(json.dumps(wf, indent=2) + "\n", encoding="utf-8")
        print("wrote", OUT / fname)


if __name__ == "__main__":
    main()
