"""Field-level extraction accuracy.

Runs the real pipeline steps (text/OCR -> guard -> LLM extraction) without the database,
against:
  generated  the demo invoices in samples/ (digital + scanned), with exact ground truth
  cord       a slice of the public CORD-v2 receipt test set (naver-clova-ix/cord-v2)

Needs the LLM, so run it in the worker container:

    docker compose run --rm -v ./eval:/eval worker sh -c \
      "pip install -q -r /eval/requirements.txt && python /eval/eval_extraction.py --dataset generated cord --limit 40"

Results go to eval/results/extraction-<dataset>.json and a one-paragraph summary is printed.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "backend", Path("/app")):
    if p.exists():
        sys.path.insert(0, str(p))

from rapidfuzz import fuzz  # noqa: E402

from app.pipeline import extract, guard, text  # noqa: E402
from app.pipeline.tasks import llm_text  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


def samples_dir() -> Path:
    for p in (ROOT / "samples", Path("/samples")):
        if (p / "ground_truth.json").exists():
            return p
    raise SystemExit("samples/ground_truth.json not found")


def norm_text(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    digits = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(digits)
    except ValueError:
        return None


def same_number(a, b, tol=0.011) -> bool:
    a, b = num(a), num(b)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def run_pipeline(data: bytes, ctype: str) -> tuple[dict, dict, int]:
    doc = text.open_document(data, ctype)
    layout = text.extract_layout(doc)
    out = guard.run_guard(doc, layout.spans)
    started = time.monotonic()
    result = extract.extract_invoice(llm_text(layout, out.excluded_span_ids))
    return result.data, result.confidence, int((time.monotonic() - started) * 1000)


# --- generated invoices -----------------------------------------------------------


def score_generated(pred: dict, gold: dict) -> dict[str, bool]:
    s = {
        "vendor_name": fuzz.ratio(norm_text(pred.get("vendor_name")), norm_text(gold["vendor_name"])) >= 90,
        "vendor_tax_id": norm_text(pred.get("vendor_tax_id")) == norm_text(gold["vendor_tax_id"]),
        "invoice_number": norm_text(pred.get("invoice_number")) == norm_text(gold["invoice_number"]),
        "invoice_date": pred.get("invoice_date") == gold["invoice_date"],
        "due_date": pred.get("due_date") == gold["due_date"],
        "currency": (pred.get("currency") or "").upper() == gold["currency"],
        "subtotal": same_number(pred.get("subtotal"), gold["subtotal"]),
        "tax": same_number(pred.get("tax") or 0, gold["tax"]),
        "total": same_number(pred.get("total"), gold["total"]),
    }
    pl, gl = pred.get("line_items") or [], gold["line_items"]
    s["line_items_count"] = len(pl) == len(gl)
    s["line_items_exact"] = s["line_items_count"] and all(
        fuzz.ratio(norm_text(p.get("description")), norm_text(g["description"])) >= 90
        and same_number(p.get("quantity"), g["quantity"])
        and same_number(p.get("unit_price"), g["unit_price"])
        and same_number(p.get("amount"), g["amount"])
        for p, g in zip(pl, gl)
    )
    return s


def eval_generated(limit: int | None, only: list[str] | None = None) -> dict:
    sd = samples_dir()
    truth = json.loads((sd / "ground_truth.json").read_text(encoding="utf-8"))
    items = [(n, m) for n, m in truth.items() if not m["poisoned"]][: limit or None]
    previous: dict[str, dict] = {}
    if only:
        # Re-run just these documents and merge into the previous results file.
        prev_file = RESULTS / "extraction-generated.json"
        if prev_file.exists():
            previous = {r["name"]: r for r in json.loads(prev_file.read_text(encoding="utf-8"))["rows"]}
        items = [(n, m) for n, m in items if n in only]
    rows = []
    for name, meta in items:
        ctype = text.guess_content_type(name, None)
        try:
            pred, conf, ms = run_pipeline((sd / name).read_bytes(), ctype)
            scores = score_generated(pred, meta["expected"])
            rows.append({"name": name, "kind": meta["kind"], "ms": ms, "scores": scores, "pred": pred})
        except Exception as exc:
            rows.append({"name": name, "kind": meta["kind"], "error": str(exc)[:300]})
        print(f"  {name}: {'error' if 'error' in rows[-1] else sum(rows[-1]['scores'].values())}/{len(rows[-1].get('scores', {})) or '-'}")
    if previous:
        previous.update({r["name"]: r for r in rows})
        rows = list(previous.values())
    return summarize("generated", rows)


# --- CORD -------------------------------------------------------------------------


def eval_cord(limit: int) -> dict:
    from datasets import load_dataset

    ds = load_dataset("naver-clova-ix/cord-v2", split="test")
    rows = []
    for i, ex in enumerate(ds.select(range(min(limit, len(ds))))):
        gt = json.loads(ex["ground_truth"])["gt_parse"]
        total = (gt.get("total") or {}).get("total_price")
        sub = gt.get("sub_total") or {}
        menu = gt.get("menu") or []
        if isinstance(menu, dict):
            menu = [menu]
        buf = io.BytesIO()
        ex["image"].convert("RGB").save(buf, format="PNG")
        try:
            pred, conf, ms = run_pipeline(buf.getvalue(), "image/png")
            scores = {"total": same_number(pred.get("total"), total, tol=0.5)}
            if sub.get("subtotal_price"):
                scores["subtotal"] = same_number(pred.get("subtotal"), sub["subtotal_price"], tol=0.5)
            if sub.get("tax_price"):
                scores["tax"] = same_number(pred.get("tax"), sub["tax_price"], tol=0.5)
            pl = pred.get("line_items") or []
            scores["line_items_count"] = len(pl) == len(menu)
            names = [norm_text(m.get("nm")) for m in menu]
            got = [norm_text(p.get("description")) for p in pl]
            matched = sum(any(fuzz.ratio(n, g) >= 80 for g in got) for n in names)
            scores["line_item_names"] = bool(names) and matched == len(names)
            rows.append({"name": f"cord-test-{i}", "kind": "cord", "ms": ms, "scores": scores})
        except Exception as exc:
            rows.append({"name": f"cord-test-{i}", "kind": "cord", "error": str(exc)[:300]})
        print(f"  cord {i}: {rows[-1].get('scores') or rows[-1].get('error')}")
    return summarize("cord", rows)


# --- reporting --------------------------------------------------------------------


def summarize(dataset: str, rows: list[dict]) -> dict:
    per_field: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        for k, v in r.get("scores", {}).items():
            per_field[k].append(v)
    ok_rows = [r for r in rows if "scores" in r]
    field_acc = {k: round(sum(v) / len(v), 3) for k, v in per_field.items()}
    all_fields = [v for vs in per_field.values() for v in vs]
    summary = {
        "dataset": dataset,
        "documents": len(rows),
        "errors": len(rows) - len(ok_rows),
        "field_accuracy": field_acc,
        "overall_field_accuracy": round(sum(all_fields) / len(all_fields), 3) if all_fields else None,
        "fully_correct_documents": sum(all(r["scores"].values()) for r in ok_rows),
        "median_llm_ms": sorted(r["ms"] for r in ok_rows)[len(ok_rows) // 2] if ok_rows else None,
        "model": extract.get_settings().llm_model,
        "date": date.today().isoformat(),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"extraction-{dataset}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return summary


def sentence(s: dict) -> str:
    worst = sorted(s["field_accuracy"].items(), key=lambda kv: kv[1])[:2]
    return (
        f"On {s['documents']} {s['dataset']} documents, {s['model']} got {100 * (s['overall_field_accuracy'] or 0):.0f}% of fields right "
        f"and {s['fully_correct_documents']} documents fully right; the weakest fields were "
        + ", ".join(f"{k} ({100 * v:.0f}%)" for k, v in worst)
        + f". Median extraction time was {(s['median_llm_ms'] or 0) / 1000:.1f} s."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", nargs="+", default=["generated"], choices=["generated", "cord"])
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--only", nargs="*", help="generated: re-run only these sample names and merge with the last results")
    args = ap.parse_args()
    for ds in args.dataset:
        print(f"== {ds}")
        s = eval_generated(None, args.only) if ds == "generated" else eval_cord(args.limit)
        print(json.dumps(s, indent=2))
        print(sentence(s))


if __name__ == "__main__":
    main()
