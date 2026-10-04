"""Injection-guard evaluation: detection rate on poisoned invoices, false positives on clean ones.

    python eval/eval_guard.py                 # local, cheap detectors only
    python eval/eval_guard.py --random 100    # plus 100 randomised invoices per class
    docker compose run --rm -v ./eval:/eval worker python /eval/eval_guard.py --ocr --classifier

The randomised set uses samples/generate.py: random vendor, items, prices and dates, with
each poisoning technique applied to its own copy. --ocr turns on the OCR layer-diff check,
--classifier runs Prompt Guard 2 (needs HF_TOKEN).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Repo layout locally; inside the worker image the code is at /app and the samples at /samples.
for p in (ROOT / "backend", Path("/app"), ROOT / "samples", Path("/samples")):
    if p.exists():
        sys.path.insert(0, str(p))

import generate  # noqa: E402

TECHNIQUES = ("white_text", "tiny_font", "off_page")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=50, help="randomised invoices per class (clean and each technique)")
    ap.add_argument("--ocr", action="store_true", help="enable OCR layer-diff detector")
    ap.add_argument("--classifier", action="store_true", help="enable Prompt Guard 2 classifier")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "guard.json"))
    args = ap.parse_args()
    if not args.ocr:
        os.environ["OCR_ENGINE"] = "none"

    from app.pipeline import guard, ocr, text

    ocr_fn = (lambda png: (r := ocr.ocr_png(png)) and r.plain_text) if args.ocr else None
    scorer = guard.prompt_guard_scores if args.classifier else None

    cases: list[tuple[str, bytes, str, bool, str | None]] = []  # name, bytes, ctype, poisoned, technique
    samples_dir = ROOT / "samples" if (ROOT / "samples" / "ground_truth.json").exists() else Path("/samples")
    truth = json.loads((samples_dir / "ground_truth.json").read_text(encoding="utf-8"))
    for name, meta in truth.items():
        cases.append((f"samples/{name}", (samples_dir / name).read_bytes(), text.guess_content_type(name, None), meta["poisoned"], meta["poison_technique"]))

    rng = random.Random(args.seed)
    for i in range(args.random):
        spec = generate.random_spec(rng, i)
        cases.append((f"random/clean_{i}", generate.render(spec), "application/pdf", False, None))
        for t in TECHNIQUES:
            spec = generate.random_spec(rng, i, poison=t)
            cases.append((f"random/{t}_{i}", generate.render(spec), "application/pdf", True, t))

    results = []
    started = time.monotonic()
    for name, data, ctype, poisoned, technique in cases:
        doc = text.open_document(data, ctype)
        layout = text.extract_layout(doc)
        has_layer = any(s["source"] == "text_layer" for s in layout.spans)
        out = guard.run_guard(doc, layout.spans, ocr_fn=ocr_fn if has_layer else None, scorer=scorer)
        detectors = sorted({s["detector"] for s in out.signals if s["strength"] == "strong"})
        results.append({"name": name, "poisoned": poisoned, "technique": technique, "flagged": out.flagged, "detectors": detectors})
    elapsed = time.monotonic() - started

    pos = [r for r in results if r["poisoned"]]
    neg = [r for r in results if not r["poisoned"]]
    tp = sum(r["flagged"] for r in pos)
    fp = sum(r["flagged"] for r in neg)
    by_tech = {t: (sum(r["flagged"] for r in pos if r["technique"] == t), sum(1 for r in pos if r["technique"] == t)) for t in TECHNIQUES}
    detector_hits = Counter(d for r in pos for d in r["detectors"])
    summary = {
        "poisoned": len(pos),
        "detected": tp,
        "detection_rate": round(tp / len(pos), 4) if pos else None,
        "clean": len(neg),
        "false_positives": fp,
        "false_positive_rate": round(fp / len(neg), 4) if neg else None,
        "by_technique": {t: {"detected": a, "total": b} for t, (a, b) in by_tech.items()},
        "detectors_firing_on_poisoned": dict(detector_hits),
        "ocr_diff": args.ocr,
        "classifier": args.classifier,
        "seconds": round(elapsed, 1),
        "missed": [r["name"] for r in pos if not r["flagged"]],
        "false_positive_docs": [r["name"] for r in neg if r["flagged"]],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print()
    print(
        f"The guard flagged {tp} of {len(pos)} poisoned invoices ({100 * tp / max(1, len(pos)):.0f}%) "
        f"and {fp} of {len(neg)} clean ones ({100 * fp / max(1, len(neg)):.1f}% false positives)."
    )


if __name__ == "__main__":
    main()
