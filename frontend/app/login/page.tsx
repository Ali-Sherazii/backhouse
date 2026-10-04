"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";
import { Button, ErrorNote, Spinner } from "@/components/ui";

const DEMO = [
  { email: "reviewer@demo.backhouse", role: "Reviewer", note: "Upload, review, approve" },
  { email: "admin@demo.backhouse", role: "Admin", note: "Also manages vendors" },
];
const DEMO_PASSWORD = "demo1234";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState(DEMO[0].email);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-ink p-12 text-stone-200 lg:flex">
        <Logo light />
        <div className="max-w-md space-y-5">
          <h1 className="text-3xl font-semibold leading-tight text-white">Supplier invoices, read, checked and booked.</h1>
          <ul className="space-y-3 text-sm leading-relaxed text-stone-300">
            <li>• Reads PDFs, scans and phone photos with a local open-weight model.</li>
            <li>• Checks the maths, dates, vendor, duplicates and price changes.</li>
            <li>• Screens every document for hidden prompt-injection text before the model sees it.</li>
            <li>• Anything uncertain goes to a person. Approved bills go straight into Odoo.</li>
          </ul>
        </div>
        <p className="text-xs text-stone-500">Open source, self-hosted. No invoice leaves the server.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm space-y-8">
          <div className="lg:hidden">
            <Logo />
          </div>
          <div>
            <h2 className="text-xl font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-ink-muted">This is a public demo. Use one of the accounts below.</p>
          </div>

          <form onSubmit={submit} className="space-y-4">
            <label className="block space-y-1">
              <span className="text-sm font-medium">Email</span>
              <input className="field-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-medium">Password</span>
              <input className="field-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            {error && <ErrorNote>{error}</ErrorNote>}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy && <Spinner />} Sign in
            </Button>
          </form>

          <div className="rounded-xl border border-dashed border-amber-300 bg-brand-soft/60 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-dark">Demo accounts</p>
            <p className="mt-1 text-xs text-ink-soft">
              The reviewer login also opens Odoo and Langfuse, read-only, so you can follow an invoice to its bill and its trace.
            </p>
            <ul className="mt-3 space-y-2">
              {DEMO.map((d) => (
                <li key={d.email}>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail(d.email);
                      setPassword(DEMO_PASSWORD);
                    }}
                    className="w-full rounded-lg bg-white/80 px-3 py-2 text-left text-sm ring-1 ring-amber-200 transition hover:bg-white"
                  >
                    <span className="font-medium">{d.role}</span>
                    <span className="ml-2 text-ink-muted">{d.note}</span>
                    <span className="mt-0.5 block font-mono text-xs text-ink-soft">
                      {d.email} / {DEMO_PASSWORD}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </main>
  );
}

function Logo({ light }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-lg font-bold text-white">B</span>
      <span className={light ? "text-lg font-semibold text-white" : "text-lg font-semibold"}>Backhouse</span>
    </div>
  );
}
