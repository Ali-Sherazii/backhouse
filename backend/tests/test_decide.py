from app.models import DocStatus
from app.pipeline.decide import decide
from app.pipeline.validate import BLOCKING, WARNING, CheckResult

HIGH = {k: 0.97 for k in ("vendor_name", "invoice_number", "invoice_date", "currency", "total")}


def passing():
    return [CheckResult("line_items_sum", True, ""), CheckResult("price_change", True, "", severity=WARNING)]


def test_auto_approves_when_everything_is_clean(invoice):
    d = decide(guard_flagged=False, checks=passing(), data=invoice, confidence=HIGH, threshold=0.85)
    assert d.status == DocStatus.APPROVED and d.auto_approved and not d.reasons


def test_guard_flag_forces_review(invoice):
    d = decide(guard_flagged=True, checks=passing(), data=invoice, confidence=HIGH, threshold=0.85)
    assert d.status == DocStatus.NEEDS_REVIEW
    assert any("guard" in r.lower() for r in d.reasons)


def test_blocking_failure_forces_review(invoice):
    checks = passing() + [CheckResult("subtotal_plus_tax", False, "nope", severity=BLOCKING)]
    d = decide(guard_flagged=False, checks=checks, data=invoice, confidence=HIGH, threshold=0.85)
    assert d.status == DocStatus.NEEDS_REVIEW


def test_warning_does_not_block(invoice):
    checks = [CheckResult("price_change", False, "salmon +29%", severity=WARNING)]
    d = decide(guard_flagged=False, checks=checks, data=invoice, confidence=HIGH, threshold=0.85)
    assert d.status == DocStatus.APPROVED


def test_low_confidence_forces_review(invoice):
    conf = {**HIGH, "total": 0.84}
    d = decide(guard_flagged=False, checks=passing(), data=invoice, confidence=conf, threshold=0.85)
    assert d.status == DocStatus.NEEDS_REVIEW
    assert any("total" in r for r in d.reasons)


def test_confidence_at_threshold_is_enough(invoice):
    conf = {**HIGH, "total": 0.85}
    assert decide(guard_flagged=False, checks=passing(), data=invoice, confidence=conf, threshold=0.85).auto_approved


def test_missing_required_field_forces_review(invoice):
    invoice["invoice_number"] = None
    d = decide(guard_flagged=False, checks=passing(), data=invoice, confidence=HIGH, threshold=0.85)
    assert d.status == DocStatus.NEEDS_REVIEW


def test_optional_field_confidence_is_ignored(invoice):
    conf = {**HIGH, "due_date": 0.1, "vendor_tax_id": 0.2}
    assert decide(guard_flagged=False, checks=passing(), data=invoice, confidence=conf, threshold=0.85).auto_approved
