"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("tax_id", sa.String(100)),
        sa.Column("odoo_partner_id", sa.Integer),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_vendors_tenant_id", "vendors", ["tenant_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("minio_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("processed_at", TS),
        sa.Column("processing_ms", sa.Integer),
        sa.Column("page_count", sa.Integer),
        sa.Column("text_source", sa.String(20)),
        sa.Column("layout", postgresql.JSONB),
        sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id")),
        sa.Column("invoice_number", sa.String(100)),
        sa.Column("auto_approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("odoo_bill_id", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("email_from", sa.String(320)),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id")),
    )
    for col in ("tenant_id", "sha256", "status", "created_at", "vendor_id", "invoice_number"):
        op.create_index(f"ix_documents_{col}", "documents", [col])

    op.create_table(
        "extractions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("field_confidence", postgresql.JSONB, nullable=False),
        sa.Column("field_boxes", postgresql.JSONB, nullable=False),
        sa.Column("model", sa.String(100)),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("langfuse_trace_id", sa.String(100)),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("data", postgresql.JSONB),
    )
    op.create_index("ix_checks_document_id", "checks", ["document_id"])

    op.create_table(
        "guard_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("flagged", sa.Boolean, nullable=False),
        sa.Column("signals", postgresql.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("item_name_normalized", sa.String(300), nullable=False),
        sa.Column("unit_price", sa.Float, nullable=False),
        sa.Column("invoice_date", sa.Date),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("document_id", "item_name_normalized"),
    )
    op.create_index("ix_price_history_vendor_id", "price_history", ["vendor_id"])
    op.create_index("ix_price_history_item_name_normalized", "price_history", ["item_name_normalized"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column("at", TS, nullable=False),
    )
    op.create_index("ix_audit_log_document_id", "audit_log", ["document_id"])


def downgrade() -> None:
    for table in ("audit_log", "price_history", "guard_results", "checks", "extractions", "documents", "vendors", "users", "tenants"):
        op.drop_table(table)
