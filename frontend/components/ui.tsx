import Link from "next/link";
import type { ReactNode } from "react";
import { STATUS_LABEL } from "@/lib/format";
import type { Status } from "@/lib/types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Card({ title, action, children, className }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-paper-line bg-paper-card shadow-card", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-paper-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const STATUS_STYLE: Record<Status, string> = {
  queued: "bg-stone-100 text-stone-700 ring-stone-300",
  processing: "bg-sky-50 text-sky-800 ring-sky-200",
  needs_review: "bg-amber-50 text-amber-800 ring-amber-300",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  exported: "bg-emerald-600 text-white ring-emerald-700",
  rejected: "bg-stone-200 text-stone-600 ring-stone-300",
  failed: "bg-red-50 text-red-700 ring-red-200",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", STATUS_STYLE[status])}>
      {status === "processing" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-500" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function FlagBadge() {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">
      <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor" aria-hidden><path d="M3 2a1 1 0 0 1 1 1v.5c3-1.5 5.5 1.5 9 0V11c-3.5 1.5-6-1.5-9 0v6a1 1 0 1 1-2 0V3a1 1 0 0 1 1-1z" /></svg>
      Guard
    </span>
  );
}

export function Button({
  children,
  variant = "primary",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" | "success" }) {
  const styles = {
    primary: "bg-ink text-white hover:bg-ink-soft",
    secondary: "bg-white text-ink ring-1 ring-inset ring-paper-line hover:bg-stone-50",
    danger: "bg-white text-red-700 ring-1 ring-inset ring-red-200 hover:bg-red-50",
    ghost: "text-ink-soft hover:bg-stone-100",
    success: "bg-emerald-700 text-white hover:bg-emerald-800",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        styles,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx("inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent", className)} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-ink-muted">{children}</p>;
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{children}</div>;
}

export function Confidence({ value, ungrounded }: { value: number | undefined; ungrounded?: boolean }) {
  if (value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = value >= 0.85 ? "text-emerald-700 bg-emerald-50" : value >= 0.6 ? "text-amber-800 bg-amber-50" : "text-red-700 bg-red-50";
  return (
    <span
      className={cx("rounded px-1.5 py-0.5 font-mono text-[11px] tabular-nums", tone)}
      title={ungrounded ? "The model's value was not found on the page, so confidence was capped" : "Model confidence"}
    >
      {pct}%{ungrounded ? " · not on page" : ""}
    </span>
  );
}

export function DocLink({ id, children, review }: { id: number; children: ReactNode; review?: boolean }) {
  return (
    <Link href={review ? `/documents/${id}/review` : `/documents/${id}`} className="font-medium text-ink hover:text-brand hover:underline">
      {children}
    </Link>
  );
}
