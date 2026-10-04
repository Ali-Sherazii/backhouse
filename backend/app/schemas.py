"""Pydantic models.

`InvoiceExtraction` doubles as the JSON schema handed to the LLM (Ollama `format`),
so every field is required-but-nullable: the grammar forces the model to emit every key.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

SCALAR_FIELDS = (
    "vendor_name",
    "vendor_tax_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "discount",
    "tax",
    "total",
)
REQUIRED_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "currency", "total")


class LineItem(BaseModel):
    description: str = Field(description="Item description exactly as printed")
    quantity: float | None = Field(description="Quantity as a number")
    unit_price: float | None = Field(description="Price per unit as a number, no currency symbol")
    amount: float | None = Field(description="Line total as a number, no currency symbol")


class FieldConfidence(BaseModel):
    """How sure the model is that each value was read correctly, 0.0 to 1.0."""

    vendor_name: float
    vendor_tax_id: float
    invoice_number: float
    invoice_date: float
    due_date: float
    currency: float
    line_items: float
    subtotal: float
    discount: float
    tax: float
    total: float


class InvoiceExtraction(BaseModel):
    vendor_name: str | None = Field(description="Name of the supplier that issued the invoice")
    vendor_tax_id: str | None = Field(description="Supplier VAT / tax / EIN number, if printed")
    invoice_number: str | None = Field(description="Invoice number exactly as printed")
    invoice_date: str | None = Field(description="Invoice date as YYYY-MM-DD")
    due_date: str | None = Field(description="Payment due date as YYYY-MM-DD, null if not printed")
    currency: str | None = Field(description="ISO 4217 code such as USD, EUR, GBP")
    line_items: list[LineItem]
    subtotal: float | None = Field(description="Sum of the line items, before any discount and tax")
    discount: float | None = Field(description="Total discount as a positive number, null if there is none")
    tax: float | None = Field(description="Total tax amount")
    total: float | None = Field(description="Amount due including tax")
    confidence: FieldConfidence


class InvoiceFields(BaseModel):
    """Invoice data without confidences: what a reviewer edits and approves."""

    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    line_items: list[LineItem] = []
    subtotal: float | None = None
    discount: float | None = None
    tax: float | None = None
    total: float | None = None


# --- API --------------------------------------------------------------------


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    tenant_id: int


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VendorIn(BaseModel):
    name: str
    aliases: list[str] = []
    tax_id: str | None = None


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    aliases: list[str]
    tax_id: str | None
    odoo_partner_id: int | None


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    source: str
    status: str
    created_at: datetime
    processed_at: datetime | None
    processing_ms: int | None
    vendor_name: str | None = None
    invoice_number: str | None = None
    total: float | None = None
    currency: str | None = None
    flagged: bool = False
    auto_approved: bool = False
    warnings: int = 0
    failed_checks: int = 0


class ApproveIn(BaseModel):
    fields: InvoiceFields | None = None
    note: str | None = None


class RejectIn(BaseModel):
    reason: str | None = None


class ExportedIn(BaseModel):
    document_id: int
    odoo_bill_id: int
    odoo_partner_id: int | None = None
