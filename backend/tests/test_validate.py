from datetime import date

from app.pipeline.validate import (
    BLOCKING,
    WARNING,
    CheckContext,
    VendorRef,
    check_dates,
    check_duplicate_file,
    check_duplicate_invoice,
    check_line_math,
    check_line_sum,
    check_price_change,
    check_totals,
    check_vendor,
    match_vendor,
    normalize_item,
    run_checks,
)

TODAY = date(2026, 10, 4)
GREEN = VendorRef(1, "Green Valley Produce Ltd", ["Green Valley Produce", "Green Valley"], "47-2918365")
HARBOR = VendorRef(2, "Harbor Fresh Seafood Co.", ["Harbor Fresh"], "93-4417260")


def ctx(**kw) -> CheckContext:
    return CheckContext(vendors=[GREEN, HARBOR], today=TODAY, **kw)


# --- sums ---------------------------------------------------------------------


def test_line_sum_passes(invoice):
    assert check_line_sum(invoice).passed


def test_line_sum_within_tolerance(invoice):
    invoice["subtotal"] = 100.02
    assert check_line_sum(invoice).passed


def test_line_sum_fails_outside_tolerance(invoice):
    invoice["subtotal"] = 100.03
    r = check_line_sum(invoice)
    assert not r.passed and r.severity == BLOCKING
    assert "100.00" in r.detail and "100.03" in r.detail


def test_line_sum_without_items_fails(invoice):
    invoice["line_items"] = []
    assert not check_line_sum(invoice).passed


def test_line_sum_falls_back_to_total_minus_tax(invoice):
    invoice["subtotal"] = None
    assert check_line_sum(invoice).passed
    invoice["total"] = 130.0
    assert not check_line_sum(invoice).passed


def test_totals_pass(invoice):
    assert check_totals(invoice).passed


def test_totals_fail(invoice):
    invoice["total"] = 118.0
    assert not check_totals(invoice).passed


def test_totals_missing_total(invoice):
    invoice["total"] = None
    assert not check_totals(invoice).passed


def test_totals_with_discount(invoice):
    # Subtotal 100.00 - discount 10.00 + tax 8.00 = 98.00
    invoice["discount"], invoice["total"] = 10.0, 98.0
    r = check_totals(invoice)
    assert r.passed and "discount 10.00" in r.detail
    # printed as "-10.00": same meaning
    invoice["discount"] = -10.0
    assert check_totals(invoice).passed


def test_totals_fail_when_discount_is_missed(invoice):
    invoice["total"] = 98.0  # the invoice had a discount the extraction didn't capture
    assert not check_totals(invoice).passed


def test_line_sum_fallback_accounts_for_discount(invoice):
    invoice["subtotal"], invoice["discount"], invoice["total"] = None, 10.0, 98.0
    assert check_line_sum(invoice).passed


def test_totals_treat_missing_tax_as_zero(invoice):
    invoice["tax"], invoice["total"] = None, 100.0
    assert check_totals(invoice).passed


# --- line math ----------------------------------------------------------------


def test_line_math_passes(invoice):
    assert check_line_math(invoice).passed


def test_line_math_rounding_is_tolerated(invoice):
    invoice["line_items"] = [{"description": "x", "quantity": 3, "unit_price": 2.333, "amount": 7.0}]
    assert check_line_math(invoice).passed


def test_line_math_flags_bad_line(invoice):
    invoice["line_items"][1]["amount"] = 45.0
    r = check_line_math(invoice)
    assert not r.passed
    assert r.data["lines"][0]["line"] == 2


def test_line_math_skips_incomplete_lines(invoice):
    invoice["line_items"][0]["quantity"] = None
    assert check_line_math(invoice).passed


# --- dates --------------------------------------------------------------------


def test_dates_valid(invoice):
    assert check_dates(invoice, TODAY).passed


def test_dates_future_invoice(invoice):
    invoice["invoice_date"] = "2026-12-01"
    invoice["due_date"] = None
    r = check_dates(invoice, TODAY)
    assert not r.passed and "future" in r.detail


def test_dates_due_before_invoice(invoice):
    invoice["due_date"] = "2026-08-01"
    assert not check_dates(invoice, TODAY).passed


def test_dates_unparseable(invoice):
    invoice["invoice_date"] = "September 1st"
    assert not check_dates(invoice, TODAY).passed


def test_dates_missing_due_is_fine(invoice):
    invoice["due_date"] = None
    assert check_dates(invoice, TODAY).passed


# --- vendor -------------------------------------------------------------------


def test_vendor_exact():
    v, score = match_vendor("Green Valley Produce Ltd", None, [GREEN, HARBOR])
    assert v is GREEN and score >= 95


def test_vendor_fuzzy_alias():
    v, _ = match_vendor("GREEN VALLEY PRODUCE LTD.", None, [GREEN, HARBOR])
    assert v is GREEN


def test_vendor_by_tax_id_even_if_name_differs():
    v, score = match_vendor("GVP Wholesale", "47 2918365", [GREEN, HARBOR])
    assert v is GREEN and score == 100


def test_vendor_unknown(invoice):
    invoice["vendor_name"], invoice["vendor_tax_id"] = "Totally New Supplier", None
    r, v = check_vendor(invoice, ctx())
    assert not r.passed and v is None


# --- duplicates ---------------------------------------------------------------


def test_duplicate_file():
    assert check_duplicate_file(ctx()).passed
    r = check_duplicate_file(ctx(duplicate_file_of=7))
    assert not r.passed and "#7" in r.detail


def test_duplicate_invoice_number(invoice):
    seen = {(1, "GV-2000"): 3}
    c = ctx(invoice_seen=lambda v, n: seen.get((v, n)))
    r = check_duplicate_invoice(invoice, GREEN, c)
    assert not r.passed and "#3" in r.detail
    invoice["invoice_number"] = "GV-2001"
    assert check_duplicate_invoice(invoice, GREEN, c).passed


def test_same_number_different_vendor_is_not_duplicate(invoice):
    c = ctx(invoice_seen=lambda v, n: 3 if v == 2 else None)
    assert check_duplicate_invoice(invoice, GREEN, c).passed


def test_missing_invoice_number_fails(invoice):
    invoice["invoice_number"] = None
    assert not check_duplicate_invoice(invoice, GREEN, ctx()).passed


# --- price change -------------------------------------------------------------


def test_price_change_warns_over_10_percent(invoice):
    prices = {(1, "roma tomatoes 25 lb case"): (25.0, "2026-08-01")}
    r = check_price_change(invoice, GREEN, ctx(last_price=lambda v, i: prices.get((v, i))))
    assert not r.passed
    assert r.severity == WARNING
    assert r.data["changes"][0]["change_pct"] == 20.0


def test_price_change_under_threshold(invoice):
    prices = {(1, "roma tomatoes 25 lb case"): (28.0, None)}
    assert check_price_change(invoice, GREEN, ctx(last_price=lambda v, i: prices.get((v, i)))).passed


def test_price_drop_also_warns(invoice):
    prices = {(1, "lemons 115 ct"): (50.0, None)}
    r = check_price_change(invoice, GREEN, ctx(last_price=lambda v, i: prices.get((v, i))))
    assert not r.passed and r.data["changes"][0]["change_pct"] == -20.0


def test_normalize_item():
    assert normalize_item("  Roma Tomatoes, 25-lb case ") == "roma tomatoes 25 lb case"


# --- all together -------------------------------------------------------------


def test_run_checks_all_pass(invoice):
    results, vendor = run_checks(invoice, ctx())
    assert vendor is GREEN
    assert all(r.passed for r in results), [r for r in results if not r.passed]
    assert {r.name for r in results} == {
        "duplicate_file",
        "line_items_sum",
        "subtotal_plus_tax",
        "line_math",
        "dates",
        "known_vendor",
        "duplicate_invoice_number",
        "price_change",
    }


def test_ground_truth_samples_pass_their_own_checks(truth):
    """The generated clean invoices must be internally consistent; the bad one must not be."""
    vendors = [GREEN, HARBOR] + [
        VendorRef(10 + i, n, [], t)
        for i, (n, t) in enumerate(
            [
                ("Bluebell Dairy Co.", "36-8820147"),
                ("Stone Mill Bakery", "82-1937754"),
                ("Copper Kettle Beverages", "27-6650381"),
                ("Prime Cut Meats Inc.", "58-3302916"),
            ]
        )
    ]
    for name, meta in truth.items():
        results, _ = run_checks(meta["expected"], CheckContext(vendors=vendors, today=TODAY))
        failed = {r.name for r in results if not r.passed}
        if meta["kind"] == "bad_totals":
            assert "line_items_sum" in failed, name
        else:
            assert not failed, (name, failed)
