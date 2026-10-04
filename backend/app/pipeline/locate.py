"""Tie extracted values back to the page.

For each field we look for the value in the text spans. A hit gives the review screen
a box to highlight. A miss means the model produced a value that isn't printed on the
document, so its confidence is capped below the auto-approve threshold, whatever the
model claimed.
"""

from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from app.schemas import SCALAR_FIELDS

UNGROUNDED_CAP = 0.5
CURRENCY_MARKS = {
    "USD": ("$", "usd", "us$"),
    "EUR": ("€", "eur"),
    "GBP": ("£", "gbp"),
    "CAD": ("cad", "c$"),
    "AUD": ("aud", "a$"),
    "INR": ("₹", "inr", "rs"),
    "PKR": ("pkr", "rs"),
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def number_variants(x: float) -> set[str]:
    out = {f"{x:.2f}", f"{x:,.2f}"}
    if float(x).is_integer():
        out |= {str(int(x)), f"{int(x):,}"}
    out.add(f"{x:.3f}".rstrip("0").rstrip("."))
    eu = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    out.add(eu)
    return {v for v in out if v}


def date_variants(iso: str) -> set[str]:
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return {iso}
    mon, month = d.strftime("%b"), d.strftime("%B")
    raw = {
        d.isoformat(),
        d.strftime("%d/%m/%Y"),
        d.strftime("%m/%d/%Y"),
        f"{d.month}/{d.day}/{d.year}",
        f"{d.day}/{d.month}/{d.year}",
        d.strftime("%d.%m.%Y"),
        d.strftime("%d-%m-%Y"),
        f"{d.day} {mon} {d.year}",
        f"{d.day:02d} {mon} {d.year}",
        f"{d.day} {month} {d.year}",
        f"{mon} {d.day} {d.year}",
        f"{mon} {d.day:02d} {d.year}",
        f"{month} {d.day} {d.year}",
        f"{month} {d.day:02d} {d.year}",
        f"{d.day}-{mon}-{d.year}",
        f"{d.day:02d}-{mon}-{d.year}",
        d.strftime("%d/%m/%y"),
        d.strftime("%m/%d/%y"),
    }
    return {norm(v) for v in raw}


def _box(sp: dict) -> dict:
    return {"page": sp["page"], "bbox": sp["bbox"]}


def find_text(value: str, spans: list[dict]) -> list[dict]:
    target = norm(value)
    if len(target) < 2:
        return []
    exact = [_box(sp) for sp in spans if target in norm(sp["text"])]
    if exact:
        return exact
    if len(target) >= 6:
        scored = [(fuzz.partial_ratio(target, norm(sp["text"])), sp) for sp in spans if len(norm(sp["text"])) >= 3]
        best = [sp for score, sp in scored if score >= 90]
        return [_box(sp) for sp in best[:3]]
    return []


_num_re = re.compile(r"-?\d[\d,.]*\d|\d")


def find_number(value: float, spans: list[dict]) -> list[dict]:
    variants = number_variants(abs(value))
    hits = []
    for sp in spans:
        for tok in _num_re.findall(sp["text"]):
            if tok.strip().lstrip("-") in variants:
                hits.append(_box(sp))
                break
    return hits


def find_date(value: str, spans: list[dict]) -> list[dict]:
    variants = date_variants(value)
    hits = []
    for sp in spans:
        t = norm(sp["text"])
        if any(v and v in t for v in variants):
            hits.append(_box(sp))
    return hits


def find_currency(code: str, spans: list[dict]) -> list[dict]:
    marks = CURRENCY_MARKS.get(code.upper(), (code.lower(),))
    hits = []
    for sp in spans:
        low = sp["text"].lower()
        if any((m in low) if not m.isalpha() else re.search(rf"\b{re.escape(m)}\b", low) for m in marks):
            hits.append(_box(sp))
    return hits[:3]


DISCOUNT_LABELS = ("discount", "rebate", "credit", "promo")


def _amount(token: str) -> float | None:
    token = token.strip().lstrip("-")
    if "," in token and "." not in token and len(token.split(",")[-1]) == 2:
        token = token.replace(",", ".")  # 179,84
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def find_discount(spans: list[dict]) -> tuple[float, dict] | None:
    """A "Discount ... -$179.84" row: a label span, and the right-most amount on its row."""
    for sp in spans:
        if not any(k in sp["text"].lower() for k in DISCOUNT_LABELS):
            continue
        cy = (sp["bbox"][1] + sp["bbox"][3]) / 2
        h = max(sp["bbox"][3] - sp["bbox"][1], 0.004)
        row = [sp] + [
            o
            for o in spans
            if o is not sp
            and o["page"] == sp["page"]
            and o["bbox"][0] >= sp["bbox"][0]
            and abs((o["bbox"][1] + o["bbox"][3]) / 2 - cy) < 0.6 * h
        ]
        amounts = [(o["bbox"][2], v, o) for o in row for t in _num_re.findall(o["text"]) if (v := _amount(t))]
        if amounts:
            _, value, where = max(amounts, key=lambda a: a[0])
            return value, _box(where)
    return None


def fill_missing_discount(data: dict, confidence: dict, boxes: dict, spans: list[dict]) -> bool:
    """Small models sometimes skip the discount. Take it from the page, but only when it makes
    subtotal - discount + tax equal the total, so it can't introduce an error."""
    if data.get("discount") or data.get("subtotal") is None or data.get("total") is None:
        return False
    found = find_discount(spans)
    if found is None:
        return False
    value, box = found
    if abs(data["subtotal"] - value + (data.get("tax") or 0) - data["total"]) > 0.02 + 1e-9:
        return False
    data["discount"] = value
    confidence["discount"] = 0.9
    boxes["discount"] = [box]
    return True


def locate_field(name: str, value, spans: list[dict]) -> list[dict]:
    if value is None or value == "":
        return []
    if name in ("subtotal", "discount", "tax", "total"):
        return find_number(float(value), spans)
    if name in ("invoice_date", "due_date"):
        return find_date(str(value), spans)
    if name == "currency":
        return find_currency(str(value), spans)
    return find_text(str(value), spans)


def ground(data: dict, confidence: dict, spans: list[dict]) -> tuple[dict, dict, list[str]]:
    """Return (adjusted confidence, field boxes, list of ungrounded fields)."""
    conf = {k: max(0.0, min(1.0, float(v))) for k, v in (confidence or {}).items()}
    boxes: dict[str, list[dict]] = {}
    ungrounded: list[str] = []

    for name in SCALAR_FIELDS:
        value = data.get(name)
        found = locate_field(name, value, spans)
        if found:
            boxes[name] = found[:3]
        elif value not in (None, ""):
            ungrounded.append(name)
            conf[name] = min(conf.get(name, 0.0), UNGROUNDED_CAP)

    items = data.get("line_items") or []
    item_misses = 0
    for i, item in enumerate(items):
        desc_boxes = find_text(item.get("description") or "", spans)
        if desc_boxes:
            boxes[f"line_items.{i}.description"] = desc_boxes[:1]
        else:
            item_misses += 1
        for key in ("quantity", "unit_price", "amount"):
            if item.get(key) is not None:
                b = find_number(float(item[key]), spans)
                if b:
                    boxes[f"line_items.{i}.{key}"] = b[:1]
                elif key == "amount":
                    item_misses += 1
    if items and item_misses:
        ungrounded.append("line_items")
        conf["line_items"] = min(conf.get("line_items", 0.0), UNGROUNDED_CAP)
    return conf, boxes, ungrounded
