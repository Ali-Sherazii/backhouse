from app.pipeline import locate, text
from tests.conftest import SAMPLES


def spans(name="clean_harbor_fresh_HF-2219.pdf"):
    data = (SAMPLES / name).read_bytes()
    return text.extract_layout(text.open_document(data, "application/pdf")).spans


def test_ground_truth_values_are_all_found(truth):
    meta = truth["clean_harbor_fresh_HF-2219.pdf"]
    conf = {k: 0.95 for k in ("vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date",
                              "currency", "line_items", "subtotal", "tax", "total")}
    adjusted, boxes, ungrounded = locate.ground(meta["expected"], conf, spans())
    assert ungrounded == []
    assert adjusted == conf
    for field in ("vendor_name", "invoice_number", "invoice_date", "due_date", "total", "subtotal"):
        assert boxes[field], field
        b = boxes[field][0]["bbox"]
        assert 0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1
    assert "line_items.0.description" in boxes


def test_invented_value_is_capped(truth):
    data = dict(truth["clean_harbor_fresh_HF-2219.pdf"]["expected"])
    data["total"] = 999.99
    data["invoice_number"] = "HF-9999"
    adjusted, boxes, ungrounded = locate.ground(data, {"total": 0.99, "invoice_number": 0.99}, spans())
    assert set(ungrounded) >= {"total", "invoice_number"}
    assert adjusted["total"] <= locate.UNGROUNDED_CAP
    assert "total" not in boxes


def test_date_formats():
    assert locate.norm("Sep 22, 2026") in locate.date_variants("2026-09-22")
    assert locate.norm("22/09/2026") in locate.date_variants("2026-09-22")
    assert locate.norm("2026-09-22") in locate.date_variants("2026-09-22")
    # single-digit days are printed zero-padded by many suppliers
    assert locate.norm("Oct 02, 2026") in locate.date_variants("2026-10-02")
    assert locate.norm("October 2, 2026") in locate.date_variants("2026-10-02")


def test_number_formats():
    v = locate.number_variants(1234.5)
    assert {"1234.50", "1,234.50", "1.234,50"} <= v
    assert "48" in locate.number_variants(48.0)


def test_discount_printed_with_minus_sign_is_found():
    s = [{"page": 0, "bbox": [0.5, 0.5, 0.6, 0.52], "text": "-$179.84"}]
    assert locate.locate_field("discount", 179.84, s)
    assert locate.locate_field("discount", -179.84, s)


def _row(y, *cells):
    return [{"page": 0, "bbox": [x, y, x + 0.08, y + 0.02], "text": t} for x, t in cells]


def test_missing_discount_is_filled_when_totals_confirm_it():
    spans = _row(0.59, (0.5, "Subtotal"), (0.7, "$1,798.39")) + _row(0.61, (0.5, "Discount"), (0.7, "-$179.84"))         + _row(0.63, (0.5, "Tax"), (0.7, "+$80.93")) + _row(0.66, (0.5, "Total"), (0.7, "$1,699.48"))
    data = {"subtotal": 1798.39, "discount": None, "tax": 80.93, "total": 1699.48}
    conf, boxes = {}, {}
    assert locate.fill_missing_discount(data, conf, boxes, spans)
    assert data["discount"] == 179.84 and conf["discount"] == 0.9 and boxes["discount"]


def test_discount_is_not_filled_when_totals_disagree():
    spans = _row(0.61, (0.5, "Discount"), (0.7, "-$50.00"))
    data = {"subtotal": 1798.39, "discount": None, "tax": 80.93, "total": 1699.48}
    assert not locate.fill_missing_discount(data, {}, {}, spans)
    assert data["discount"] is None


def test_credit_card_text_without_matching_amount_is_ignored():
    spans = _row(0.8, (0.1, "We accept credit cards"), (0.7, "Visa"))
    data = {"subtotal": 100.0, "discount": None, "tax": 8.0, "total": 108.0}
    assert not locate.fill_missing_discount(data, {}, {}, spans)


def test_currency_symbol_grounds_usd():
    s = [{"page": 0, "bbox": [0, 0, 1, 1], "text": "$375.90"}]
    assert locate.find_currency("USD", s)
    assert not locate.find_currency("EUR", s)
