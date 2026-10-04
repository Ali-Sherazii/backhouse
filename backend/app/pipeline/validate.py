"""Rule checks on an extraction. Pure functions: the DB lookups come in through CheckContext."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

from rapidfuzz import fuzz, process

TOLERANCE = 0.02
PRICE_CHANGE_THRESHOLD = 0.10
VENDOR_MATCH_THRESHOLD = 85

BLOCKING, WARNING = "blocking", "warning"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str = BLOCKING
    data: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class VendorRef:
    id: int
    name: str
    aliases: list[str] = field(default_factory=list)
    tax_id: str | None = None


@dataclass
class CheckContext:
    vendors: list[VendorRef]
    today: date
    duplicate_file_of: int | None = None
    # (vendor_id, invoice_number) -> id of another live document with that number, or None
    invoice_seen: Callable[[int, str], int | None] = lambda _v, _n: None
    # (vendor_id, normalised item) -> (last unit price, invoice date iso) or None
    last_price: Callable[[int, str], tuple[float, str | None] | None] = lambda _v, _i: None


def discount_of(d: dict) -> float:
    """Discounts are printed as "-179.84" or "179.84"; treat both as an amount taken off."""
    return abs(d.get("discount") or 0.0)


def close(a: float, b: float, tol: float = TOLERANCE) -> bool:
    return abs(a - b) <= tol + 1e-9


def normalize_item(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).strip()


def _norm_tax(t: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def match_vendor(name: str | None, tax_id: str | None, vendors: list[VendorRef]) -> tuple[VendorRef | None, float]:
    if tax_id and _norm_tax(tax_id):
        for v in vendors:
            if v.tax_id and _norm_tax(v.tax_id) == _norm_tax(tax_id):
                return v, 100.0
    if not name:
        return None, 0.0
    choices: dict[str, VendorRef] = {}
    for v in vendors:
        for n in [v.name, *(v.aliases or [])]:
            choices[n.lower()] = v
    if not choices:
        return None, 0.0
    best = process.extractOne(name.lower(), list(choices), scorer=fuzz.WRatio)
    if best and best[1] >= VENDOR_MATCH_THRESHOLD:
        return choices[best[0]], float(best[1])
    return None, float(best[1]) if best else 0.0


# --- individual checks ------------------------------------------------------


def check_duplicate_file(ctx: CheckContext) -> CheckResult:
    if ctx.duplicate_file_of:
        return CheckResult("duplicate_file", False, f"Same file as document #{ctx.duplicate_file_of}", data={"document_id": ctx.duplicate_file_of})
    return CheckResult("duplicate_file", True, "File not seen before")


def check_line_sum(d: dict) -> CheckResult:
    items = d.get("line_items") or []
    if not items:
        return CheckResult("line_items_sum", False, "No line items extracted")
    amounts = [i.get("amount") for i in items]
    if any(a is None for a in amounts):
        return CheckResult("line_items_sum", False, "Some line items have no amount")
    total_lines = round(sum(amounts), 2)
    subtotal = d.get("subtotal")
    if subtotal is None:
        if d.get("total") is None:
            return CheckResult("line_items_sum", False, "No subtotal or total to compare against")
        subtotal = round(d["total"] - (d.get("tax") or 0) + discount_of(d), 2)
        label = "total - tax + discount"
    else:
        label = "subtotal"
    ok = close(total_lines, subtotal)
    return CheckResult(
        "line_items_sum",
        ok,
        f"Line amounts sum to {total_lines:.2f}, {label} is {subtotal:.2f}",
        data={"lines_sum": total_lines, "expected": subtotal},
    )


def check_totals(d: dict) -> CheckResult:
    total = d.get("total")
    if total is None:
        return CheckResult("subtotal_plus_tax", False, "No total extracted")
    subtotal = d.get("subtotal")
    if subtotal is None:
        items = d.get("line_items") or []
        if items and all(i.get("amount") is not None for i in items):
            subtotal = round(sum(i["amount"] for i in items), 2)
        else:
            return CheckResult("subtotal_plus_tax", False, "No subtotal extracted")
    tax = d.get("tax") or 0.0
    discount = discount_of(d)
    computed = round(subtotal - discount + tax, 2)
    discount_text = f" - discount {discount:.2f}" if discount else ""
    return CheckResult(
        "subtotal_plus_tax",
        close(computed, total),
        f"{subtotal:.2f}{discount_text} + tax {tax:.2f} = {computed:.2f}, total is {total:.2f}",
        data={"computed": computed, "total": total},
    )


def check_line_math(d: dict) -> CheckResult:
    bad = []
    for i, item in enumerate(d.get("line_items") or []):
        q, p, a = item.get("quantity"), item.get("unit_price"), item.get("amount")
        if q is None or p is None or a is None:
            continue
        if not close(q * p, a):
            bad.append({"line": i + 1, "description": item.get("description"), "expected": round(q * p, 2), "amount": a})
    if bad:
        lines = ", ".join(f"line {b['line']} ({b['expected']:.2f} ≠ {b['amount']:.2f})" for b in bad)
        return CheckResult("line_math", False, f"quantity × unit price doesn't match amount on {lines}", data={"lines": bad})
    return CheckResult("line_math", True, "Every line's quantity × unit price matches its amount")


def check_dates(d: dict, today: date) -> CheckResult:
    inv = parse_date(d.get("invoice_date"))
    if inv is None:
        return CheckResult("dates", False, f"Invoice date missing or unreadable: {d.get('invoice_date')!r}")
    if inv > today:
        return CheckResult("dates", False, f"Invoice date {inv} is in the future")
    due_raw = d.get("due_date")
    if due_raw:
        due = parse_date(due_raw)
        if due is None:
            return CheckResult("dates", False, f"Due date unreadable: {due_raw!r}")
        if due < inv:
            return CheckResult("dates", False, f"Due date {due} is before invoice date {inv}")
        return CheckResult("dates", True, f"Invoice {inv}, due {due}")
    return CheckResult("dates", True, f"Invoice {inv}, no due date printed")


def check_vendor(d: dict, ctx: CheckContext) -> tuple[CheckResult, VendorRef | None]:
    vendor, score = match_vendor(d.get("vendor_name"), d.get("vendor_tax_id"), ctx.vendors)
    if vendor is None:
        return CheckResult("known_vendor", False, f"No known vendor matches {d.get('vendor_name')!r} (best score {score:.0f})"), None
    return (
        CheckResult("known_vendor", True, f"Matched {vendor.name} (score {score:.0f})", data={"vendor_id": vendor.id, "score": score}),
        vendor,
    )


def check_duplicate_invoice(d: dict, vendor: VendorRef | None, ctx: CheckContext) -> CheckResult:
    number = (d.get("invoice_number") or "").strip()
    if not number:
        return CheckResult("duplicate_invoice_number", False, "No invoice number extracted")
    if vendor is None:
        return CheckResult("duplicate_invoice_number", True, "Skipped: vendor unknown")
    other = ctx.invoice_seen(vendor.id, number)
    if other:
        return CheckResult(
            "duplicate_invoice_number",
            False,
            f"Invoice {number} from {vendor.name} already exists as document #{other}",
            data={"document_id": other},
        )
    return CheckResult("duplicate_invoice_number", True, f"Invoice {number} not seen before for {vendor.name}")


def check_price_change(d: dict, vendor: VendorRef | None, ctx: CheckContext) -> CheckResult:
    if vendor is None:
        return CheckResult("price_change", True, "Skipped: vendor unknown", severity=WARNING)
    changes = []
    for item in d.get("line_items") or []:
        price = item.get("unit_price")
        if price is None:
            continue
        key = normalize_item(item.get("description") or "")
        prev = ctx.last_price(vendor.id, key)
        if not prev or not prev[0]:
            continue
        old, when = prev
        delta = (price - old) / old
        if abs(delta) > PRICE_CHANGE_THRESHOLD:
            changes.append(
                {"item": item.get("description"), "old": old, "new": price, "change_pct": round(delta * 100, 1), "last_seen": when}
            )
    if changes:
        text = "; ".join(f"{c['item']}: {c['old']:.2f} → {c['new']:.2f} ({c['change_pct']:+.1f}%)" for c in changes)
        return CheckResult("price_change", False, text, severity=WARNING, data={"changes": changes})
    return CheckResult("price_change", True, "No unit price moved more than 10%", severity=WARNING)


def run_checks(d: dict, ctx: CheckContext) -> tuple[list[CheckResult], VendorRef | None]:
    vendor_check, vendor = check_vendor(d, ctx)
    results = [
        check_duplicate_file(ctx),
        check_line_sum(d),
        check_totals(d),
        check_line_math(d),
        check_dates(d, ctx.today),
        vendor_check,
        check_duplicate_invoice(d, vendor, ctx),
        check_price_change(d, vendor, ctx),
    ]
    return results, vendor
