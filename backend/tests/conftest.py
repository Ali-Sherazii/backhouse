import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND.parent / "samples"
sys.path.insert(0, str(BACKEND))
# Unit tests never touch real OCR models or external services.
os.environ.setdefault("OCR_ENGINE", "none")
os.environ.setdefault("LANGFUSE_HOST", "")


@pytest.fixture(scope="session")
def truth() -> dict:
    return json.loads((SAMPLES / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture
def invoice() -> dict:
    """A consistent invoice: 2 lines, subtotal 100.00, tax 8.00, total 108.00."""
    return {
        "vendor_name": "Green Valley Produce Ltd",
        "vendor_tax_id": "47-2918365",
        "invoice_number": "GV-2000",
        "invoice_date": "2026-09-01",
        "due_date": "2026-09-15",
        "currency": "USD",
        "line_items": [
            {"description": "Roma tomatoes 25 lb case", "quantity": 2, "unit_price": 30.0, "amount": 60.0},
            {"description": "Lemons 115 ct", "quantity": 1, "unit_price": 40.0, "amount": 40.0},
        ],
        "subtotal": 100.0,
        "tax": 8.0,
        "total": 108.0,
    }
