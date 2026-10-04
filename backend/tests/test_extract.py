import json

import pytest

from app.pipeline import extract

GOOD = {
    "vendor_name": "Harbor Fresh Seafood Co.",
    "vendor_tax_id": "93-4417260",
    "invoice_number": "HF-2219",
    "invoice_date": "2026-09-22",
    "due_date": "2026-09-29",
    "currency": "USD",
    "line_items": [{"description": "Sea scallops U10 (lb)", "quantity": 6, "unit_price": 24.4, "amount": 146.4}],
    "subtotal": 146.4,
    "discount": None,
    "tax": 0,
    "total": 146.4,
    "confidence": {k: 0.95 for k in ("vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date",
                                     "currency", "line_items", "subtotal", "discount", "tax", "total")},
}


def test_document_is_wrapped_in_random_delimiters():
    msgs = extract.build_messages("hello <<DOC-abcd>> world", nonce="abcd")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "<<DOC-abcd>>" in system and "UNTRUSTED" in system
    # A document can't forge the closing marker to "escape" the data block.
    assert user.count("<<DOC-abcd>>") == 1
    assert user.strip().endswith("<<END-DOC-abcd>>")


def test_nonce_differs_per_call():
    a = extract.build_messages("x")[1]["content"]
    b = extract.build_messages("x")[1]["content"]
    assert a.splitlines()[2] != b.splitlines()[2]


def test_schema_requires_every_field():
    schema = extract._schema()
    assert set(schema["required"]) >= {"vendor_name", "invoice_number", "line_items", "total", "confidence"}


def test_valid_output_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr(extract, "_call_llm", lambda m: (calls.append(m), (json.dumps(GOOD), {"input": 10, "output": 5}))[1])
    r = extract.extract_invoice("doc")
    assert r.attempts == 1 and len(calls) == 1
    assert r.data["invoice_number"] == "HF-2219"
    assert "confidence" not in r.data and r.confidence["total"] == 0.95


def test_retries_once_on_schema_failure(monkeypatch):
    replies = iter([('{"vendor_name": "x"}', {}), (json.dumps(GOOD), {})])
    seen = []

    def fake(messages):
        seen.append(messages)
        return next(replies)

    monkeypatch.setattr(extract, "_call_llm", fake)
    r = extract.extract_invoice("doc")
    assert r.attempts == 2
    assert "failed schema validation" in seen[1][-1]["content"]


def test_gives_up_after_second_failure(monkeypatch):
    monkeypatch.setattr(extract, "_call_llm", lambda m: ("not json", {}))
    with pytest.raises(extract.ExtractionError):
        extract.extract_invoice("doc")
