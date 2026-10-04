export type Status = "queued" | "processing" | "needs_review" | "approved" | "exported" | "rejected" | "failed";

export interface User {
  id: number;
  email: string;
  role: "admin" | "reviewer";
  tenant_id: number;
}

export interface LineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
}

export interface InvoiceFields {
  vendor_name: string | null;
  vendor_tax_id: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string | null;
  line_items: LineItem[];
  subtotal: number | null;
  discount?: number | null;
  tax: number | null;
  total: number | null;
}

export interface DocumentSummary {
  id: number;
  filename: string;
  source: "upload" | "email" | "sample";
  status: Status;
  created_at: string;
  processed_at: string | null;
  processing_ms: number | null;
  vendor_name: string | null;
  invoice_number: string | null;
  total: number | null;
  currency: string | null;
  flagged: boolean;
  auto_approved: boolean;
  warnings: number;
  failed_checks: number;
}

export interface Box {
  page: number;
  bbox: [number, number, number, number];
}

export interface Span {
  id: number;
  page: number;
  text: string;
  bbox: [number, number, number, number];
  source: "text_layer" | "ocr";
  excluded?: boolean;
}

export interface Check {
  name: string;
  passed: boolean;
  severity: "blocking" | "warning";
  detail: string | null;
  data: Record<string, unknown> | null;
}

export interface GuardSignal {
  detector: "hidden_text" | "layer_mismatch" | "classifier" | "keywords";
  strength: "strong" | "weak" | "info";
  text: string;
  page: number | null;
  bbox: [number, number, number, number] | null;
  detail: string;
}

export interface AuditEntry {
  action: string;
  user: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string;
}

export interface DocumentDetail extends DocumentSummary {
  content_type: string;
  page_count: number | null;
  text_source: string | null;
  sha256: string;
  email_from: string | null;
  error: string | null;
  odoo_bill_id: number | null;
  odoo_url: string | null;
  vendor: { id: number; name: string; odoo_partner_id: number | null } | null;
  file_url: string;
  page_urls: string[];
  layout: { pages: { width: number; height: number }[]; spans: Span[] };
  extraction: {
    data: InvoiceFields;
    field_confidence: Record<string, number> & { _ungrounded?: string[] };
    field_boxes: Record<string, Box[]>;
    model: string | null;
    latency_ms: number | null;
    langfuse_trace_id: string | null;
    trace_url: string | null;
  } | null;
  checks: Check[];
  guard: { flagged: boolean; signals: GuardSignal[] } | null;
  audit: AuditEntry[];
}

export interface PriceAlert {
  document_id: number;
  vendor_name: string | null;
  status: Status;
  detail: string;
  changes: { item: string; old: number; new: number; change_pct: number; last_seen: string | null }[];
  created_at: string;
}

export interface Stats {
  counts: Record<Status, number>;
  total: number;
  processed: number;
  auto_approved: number;
  auto_approve_rate: number | null;
  flagged: number;
  avg_processing_ms: number | null;
  recent: DocumentSummary[];
  flagged_documents: DocumentSummary[];
  price_alerts: PriceAlert[];
}

export interface Sample {
  name: string;
  kind: string;
  title: string;
  description: string;
}

export interface Vendor {
  id: number;
  name: string;
  aliases: string[];
  tax_id: string | null;
  odoo_partner_id: number | null;
}
