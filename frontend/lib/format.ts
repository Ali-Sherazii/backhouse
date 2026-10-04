import type { Status } from "./types";

export function money(value: number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(value);
  } catch {
    return `${currency ?? ""} ${value.toFixed(2)}`.trim();
  }
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function stamp(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const STATUS_LABEL: Record<Status, string> = {
  queued: "Queued",
  processing: "Processing",
  needs_review: "Needs review",
  approved: "Approved",
  exported: "In Odoo",
  rejected: "Rejected",
  failed: "Failed",
};

export const CHECK_LABEL: Record<string, string> = {
  duplicate_file: "Not a duplicate file",
  line_items_sum: "Lines add up to subtotal",
  subtotal_plus_tax: "Totals add up",
  line_math: "Qty × unit price = amount",
  dates: "Dates make sense",
  known_vendor: "Known vendor",
  duplicate_invoice_number: "Invoice number is new",
  price_change: "Prices in line with history",
  extraction: "Model output valid",
};

export const FIELD_LABEL: Record<string, string> = {
  vendor_name: "Vendor",
  vendor_tax_id: "Vendor tax ID",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  due_date: "Due date",
  currency: "Currency",
  subtotal: "Subtotal",
  discount: "Discount",
  tax: "Tax",
  total: "Total",
  line_items: "Line items",
};

export const DETECTOR_LABEL: Record<string, string> = {
  hidden_text: "Hidden text",
  layer_mismatch: "Text layer ≠ what's printed",
  classifier: "Prompt Guard classifier",
  keywords: "Instruction-like phrases",
};
