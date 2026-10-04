"use client";

import { useState } from "react";
import { api, getUser } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Vendor } from "@/lib/types";
import { Button, Card, ErrorNote } from "@/components/ui";

export default function VendorsPage() {
  const { data, error, reload } = useApi<Vendor[]>("/vendors");
  const isAdmin = getUser()?.role === "admin";
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [taxId, setTaxId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    try {
      await api("/vendors", {
        method: "POST",
        body: JSON.stringify({ name, tax_id: taxId || null, aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean) }),
      });
      setName("");
      setAliases("");
      setTaxId("");
      reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Vendors</h1>
        <p className="text-sm text-ink-muted">Extracted vendor names are fuzzy-matched against these names, aliases and tax IDs.</p>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <table className="table-base">
            <thead>
              <tr>
                <th>Name</th>
                <th>Aliases</th>
                <th>Tax ID</th>
                <th>Odoo partner</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((v) => (
                <tr key={v.id}>
                  <td className="font-medium">{v.name}</td>
                  <td className="text-ink-muted">{v.aliases.join(", ") || "—"}</td>
                  <td className="font-mono text-xs">{v.tax_id || "—"}</td>
                  <td className="text-ink-muted">{v.odoo_partner_id ? `#${v.odoo_partner_id}` : "not linked yet"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Add vendor">
          {isAdmin ? (
            <form onSubmit={add} className="space-y-3">
              <input className="field-input" placeholder="Legal name" value={name} onChange={(e) => setName(e.target.value)} required />
              <input className="field-input" placeholder="Aliases, comma separated" value={aliases} onChange={(e) => setAliases(e.target.value)} />
              <input className="field-input" placeholder="Tax ID" value={taxId} onChange={(e) => setTaxId(e.target.value)} />
              {formError && <ErrorNote>{formError}</ErrorNote>}
              <Button type="submit" className="w-full">Add vendor</Button>
            </form>
          ) : (
            <p className="text-sm text-ink-muted">Sign in as the admin demo account to add vendors. Vendors are also created automatically when a reviewer approves an invoice from a new supplier.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
