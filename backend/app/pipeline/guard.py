"""Injection guard. Runs on raw document text before any LLM call.

Detectors:
  hidden_text     spans a human can't see: colour ~ background, < 4pt, alpha 0 /
                  unpainted glyphs, outside the page box, or no ink where the span sits
  layer_mismatch  text-layer words that OCR of the rendered page doesn't find
  classifier      Meta Prompt Guard 2 on text chunks
  keywords        cheap phrase heuristics ("ignore previous", "system:", ...)

A strong signal flags the document (it goes to review with the offending text shown).
Weak signals are recorded but don't block. Flagged spans are dropped from the text the
extractor sees either way.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pymupdf as fitz
from rapidfuzz import fuzz, process

from app.config import get_settings

log = logging.getLogger(__name__)

STRONG, WEAK, INFO = "strong", "weak", "info"

MIN_FONT_PT = 4.0
COLOR_MATCH_DISTANCE = 50  # RGB euclidean, 0..441
INK_DIFF = 40  # per-channel difference that counts as ink
MIN_INK_FRACTION = 0.01
RENDER_DPI = 144
HIDDEN_STRONG_MIN_CHARS = 15
CLASSIFIER_STRONG = 0.9
CLASSIFIER_WEAK = 0.5

INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules|context|text)",
    r"\bdisregard\s+(?:all\s+|the\s+|any\s+)?(?:previous|prior|above|earlier|preceding|other)",
    r"\bforget\s+(?:all\s+|everything|your\s+)(?:previous|prior|instructions?)?",
    r"(?:^|\n)\s*(?:system|assistant|developer)\s*:",
    r"<\|?\s*(?:im_start|im_end|system|endoftext|begin_of_text)\s*\|?>",
    r"\[/?INST\]",
    r"\bapprove\s+(?:this|the)\s+(?:invoice|document|bill|payment)",
    r"\b(?:mark|set|flag)\s+(?:this|the)?\s*(?:invoice|document|bill)?\s*(?:as\s+)?(?:approved|verified|paid|trusted|safe)\b",
    r"\b(?:you\s+are\s+(?:now\s+)?|act\s+as\s+)(?:an?\s+)?(?:ai|assistant|language\s+model|llm|chatbot)",
    r"\b(?:new|updated|additional|hidden)\s+instructions?\b",
    r"\bdo\s+not\s+(?:flag|review|report|check|validate|mention)",
    r"\b(?:auto[- ]?approve|bypass\s+(?:review|validation|checks?))",
    r"\bset\s+(?:the\s+)?(?:total|amount|price)\s+to\b",
]
WEAK_PATTERNS = {
    "url": r"https?://[^\s]+|www\.[^\s]+",
    "bank_change": r"\b(?:new|updated|changed)\s+(?:bank|account|payment)\s+(?:details|information|number)",
}
_injection_re = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.IGNORECASE | re.MULTILINE)
_weak_res = {k: re.compile(p, re.IGNORECASE) for k, p in WEAK_PATTERNS.items()}


@dataclass
class GuardOutcome:
    flagged: bool
    signals: list[dict]
    excluded_span_ids: set[int] = field(default_factory=set)

    @property
    def strong(self) -> list[dict]:
        return [s for s in self.signals if s["strength"] == STRONG]


def _signal(detector: str, strength: str, text: str, page: int | None = None, bbox=None, detail: str = "") -> dict:
    return {
        "detector": detector,
        "strength": strength,
        "text": text[:600],
        "page": page,
        "bbox": bbox,
        "detail": detail,
    }


# --- hidden text -------------------------------------------------------------


def _page_raster(page: fitz.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False, colorspace=fitz.csRGB)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]


def _hex_rgb(color: str | None) -> np.ndarray:
    if not color:
        return np.array([0, 0, 0])
    c = int(color.lstrip("#"), 16)
    return np.array([(c >> 16) & 255, (c >> 8) & 255, c & 255])


def _visibility(raster: np.ndarray, pt_bbox: list[float], text_rgb: np.ndarray) -> tuple[float, float] | None:
    """Return (ink_fraction, colour distance to background) for a span, or None if off-raster."""
    scale = RENDER_DPI / 72.0
    h, w = raster.shape[:2]
    x0, y0, x1, y1 = (int(round(v * scale)) for v in pt_bbox)
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    pad = 4
    ox0, oy0, ox1, oy1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    outer = raster[oy0:oy1, ox0:ox1].reshape(-1, 3).astype(int)
    mask = np.ones((oy1 - oy0, ox1 - ox0), dtype=bool)
    mask[y0 - oy0 : y1 - oy0, x0 - ox0 : x1 - ox0] = False
    ring = outer[mask.reshape(-1)]
    bg = np.median(ring, axis=0) if len(ring) else np.array([255, 255, 255])
    region = raster[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    ink = float(np.mean(np.abs(region - bg).max(axis=1) > INK_DIFF))
    dist = float(np.linalg.norm(text_rgb - bg))
    return ink, dist


def _outside_page(pt_bbox: list[float], rect: fitz.Rect) -> bool:
    b = fitz.Rect(pt_bbox)
    if b.is_empty:
        return False
    inter = b & rect
    inside = 0.0 if inter.is_empty else inter.get_area()
    return inside < 0.5 * b.get_area()


def hidden_span_reasons(doc: fitz.Document, spans: list[dict]) -> dict[int, list[str]]:
    """Map span id -> reasons it is invisible to a human reader. Text-layer spans only."""
    reasons: dict[int, list[str]] = {}
    rasters: dict[int, np.ndarray] = {}
    for sp in spans:
        if sp.get("source") != "text_layer":
            continue
        page = doc[sp["page"]]
        why: list[str] = []
        if sp.get("size") is not None and sp["size"] < MIN_FONT_PT:
            why.append(f"font size {sp['size']}pt")
        # Unpainted (render mode 3) or alpha-0 glyphs are how scanners attach an OCR layer to a
        # page image. They're only suspicious over a blank area; invisible text sitting on printed
        # ink is left to the layer-mismatch check, which compares it with what OCR sees.
        invisible = sp.get("alpha", 255) == 0 or not sp.get("painted", True)
        if _outside_page(sp["pt"], page.rect):
            why.append("outside the page box")
        else:
            if sp["page"] not in rasters:
                rasters[sp["page"]] = _page_raster(page)
            vis = _visibility(rasters[sp["page"]], sp["pt"], _hex_rgb(sp.get("color")))
            if vis is not None:
                ink, dist = vis
                if invisible:
                    if ink < MIN_INK_FRACTION:
                        why.append("invisible text (transparent or render mode 3) over a blank area")
                else:
                    if dist < COLOR_MATCH_DISTANCE:
                        why.append(f"text colour {sp.get('color')} matches background")
                    if ink < MIN_INK_FRACTION:
                        why.append("no visible ink where the text sits")
        if why:
            reasons[sp["id"]] = why
    return reasons


def detect_hidden_text(doc: fitz.Document, spans: list[dict]) -> tuple[list[dict], set[int]]:
    reasons = hidden_span_reasons(doc, spans)
    if not reasons:
        return [], set()
    by_id = {sp["id"]: sp for sp in spans}
    hidden_text = " ".join(by_id[i]["text"] for i in reasons)
    strong = len(hidden_text.replace(" ", "")) >= HIDDEN_STRONG_MIN_CHARS or bool(_injection_re.search(hidden_text))
    signals = [
        _signal("hidden_text", STRONG if strong else WEAK, by_id[i]["text"], by_id[i]["page"], by_id[i]["bbox"], "; ".join(why))
        for i, why in reasons.items()
    ]
    return signals, set(reasons)


# --- layer mismatch ----------------------------------------------------------

_word_re = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str) -> list[str]:
    return _word_re.findall(text.lower())


def detect_layer_mismatch(
    doc: fitz.Document, spans: list[dict], ocr_fn: Callable[[bytes], str | None], skip_ids: set[int]
) -> tuple[list[dict], set[int]]:
    """Text in the PDF layer that OCR of the rendered page can't see."""
    from app.pipeline.text import render_page_png

    signals: list[dict] = []
    ids: set[int] = set()
    pages = sorted({sp["page"] for sp in spans if sp.get("source") == "text_layer"})
    for pno in pages:
        ocr_text = ocr_fn(render_page_png(doc[pno], dpi=200))
        if not ocr_text:
            continue
        seen = set(_tokens(ocr_text))
        seen_list = list(seen)

        def visible(tok: str) -> bool:
            # OCR misreads a character here and there ("lnvoice"); only a real miss counts.
            return tok in seen or (len(tok) >= 4 and process.extractOne(tok, seen_list, scorer=fuzz.ratio, score_cutoff=80) is not None)

        missing_total = 0
        page_hits = []
        for sp in spans:
            if sp["page"] != pno or sp.get("source") != "text_layer" or sp["id"] in skip_ids:
                continue
            toks = _tokens(sp["text"])
            if len(toks) < 4:
                continue
            missing = [t for t in toks if not visible(t)]
            if len(missing) / len(toks) >= 0.7:
                page_hits.append(sp)
                missing_total += len(missing)
        for sp in page_hits:
            # Painted text that OCR can't read is usually OCR noise (stamps, small print); the pixel
            # checks above already cover painted-but-hidden text. Unpainted text that differs from
            # what's printed under it is the attack this detector exists for.
            invisible = sp.get("alpha", 255) == 0 or not sp.get("painted", True)
            strength = STRONG if invisible and missing_total >= 4 else WEAK
            detail = (
                "invisible text-layer text that differs from what is printed"
                if invisible
                else "OCR could not read this text on the rendered page"
            )
            signals.append(_signal("layer_mismatch", strength, sp["text"], pno, sp["bbox"], detail))
            ids.add(sp["id"])
    return signals, ids


# --- classifier --------------------------------------------------------------


@lru_cache
def _prompt_guard():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    s = get_settings()
    token = s.hf_token or None
    tok = AutoTokenizer.from_pretrained(s.prompt_guard_model, token=token)
    model = AutoModelForSequenceClassification.from_pretrained(s.prompt_guard_model, token=token)
    model.eval()
    labels = {i: str(l).upper() for i, l in model.config.id2label.items()}
    benign = next((i for i, l in labels.items() if "BENIGN" in l or l == "LABEL_0"), 0)
    return tok, model, benign


PROMPT_GUARD_RETRY_SECONDS = 600
_prompt_guard_error: tuple[str, float] | None = None  # (message, time of failure)


def prompt_guard_scores(chunks: list[str]) -> list[float]:
    """Probability that each chunk is an injection/jailbreak. Raises if the model can't load."""
    global _prompt_guard_error
    if _prompt_guard_error and time.monotonic() - _prompt_guard_error[1] < PROMPT_GUARD_RETRY_SECONDS:
        # Don't retry a gated/missing model download for every document, but do retry later:
        # access to the gated model may be granted after the worker started.
        raise RuntimeError(_prompt_guard_error[0])
    try:
        tok, model, benign = _prompt_guard()
        import torch

        _prompt_guard_error = None
    except Exception as exc:
        _prompt_guard_error = (f"{type(exc).__name__}: {exc}"[:300], time.monotonic())
        raise
    scores: list[float] = []
    for i in range(0, len(chunks), 8):
        enc = tok(chunks[i : i + 8], return_tensors="pt", padding=True, truncation=True, max_length=512)
        with torch.no_grad():
            probs = torch.softmax(model(**enc).logits, dim=-1)
        scores.extend((1.0 - probs[:, benign]).tolist())
    return scores


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    chunks, cur = [], ""
    for line in text.splitlines():
        if len(cur) + len(line) + 1 > max_chars and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur.strip():
        chunks.append(cur)
    return chunks


def detect_classifier(text: str, scorer: Callable[[list[str]], list[float]] | None) -> list[dict]:
    if scorer is None:
        return [_signal("classifier", INFO, "", detail="classifier disabled")]
    chunks = chunk_text(text)
    if not chunks:
        return []
    try:
        scores = scorer(chunks)
    except Exception as exc:  # gated model without token, no network, ...
        log.warning("Prompt Guard unavailable: %s", exc)
        return [_signal("classifier", INFO, "", detail=f"classifier unavailable: {type(exc).__name__}")]
    out = []
    for chunk, score in zip(chunks, scores):
        if score >= CLASSIFIER_STRONG:
            out.append(_signal("classifier", STRONG, chunk, detail=f"Prompt Guard score {score:.2f}"))
        elif score >= CLASSIFIER_WEAK:
            out.append(_signal("classifier", WEAK, chunk, detail=f"Prompt Guard score {score:.2f}"))
    return out


# --- keywords ----------------------------------------------------------------


def detect_keywords(spans: list[dict]) -> tuple[list[dict], set[int]]:
    signals, ids = [], set()
    for sp in spans:
        m = _injection_re.search(sp["text"])
        if m:
            signals.append(_signal("keywords", STRONG, sp["text"], sp["page"], sp["bbox"], f"matched '{m.group(0).strip()}'"))
            ids.add(sp["id"])
            continue
        for name, rx in _weak_res.items():
            m = rx.search(sp["text"])
            if m:
                signals.append(_signal("keywords", WEAK, sp["text"], sp["page"], sp["bbox"], f"{name}: '{m.group(0)}'"))
    # Phrases split across spans: check each row of text as well.
    joined = " ".join(sp["text"] for sp in spans)
    if not ids and _injection_re.search(joined):
        m = _injection_re.search(joined)
        start = max(0, m.start() - 80)
        signals.append(_signal("keywords", STRONG, joined[start : m.end() + 80], detail=f"matched '{m.group(0).strip()}' across spans"))
    return signals, ids


# --- entry point -------------------------------------------------------------


def run_guard(
    doc: fitz.Document,
    spans: list[dict],
    *,
    ocr_fn: Callable[[bytes], str | None] | None = None,
    scorer: Callable[[list[str]], list[float]] | None = None,
) -> GuardOutcome:
    from app.pipeline.text import spans_to_text

    signals: list[dict] = []
    excluded: set[int] = set()

    hidden, hidden_ids = detect_hidden_text(doc, spans)
    signals += hidden
    excluded |= hidden_ids

    if ocr_fn is not None:
        mismatch, mismatch_ids = detect_layer_mismatch(doc, spans, ocr_fn, skip_ids=hidden_ids)
        signals += mismatch
        excluded |= mismatch_ids

    kw, kw_ids = detect_keywords(spans)
    signals += kw
    excluded |= kw_ids

    # The classifier sees everything, hidden spans included: that's where injections live.
    signals += detect_classifier(spans_to_text(spans), scorer)

    flagged = any(s["strength"] == STRONG for s in signals)
    return GuardOutcome(flagged=flagged, signals=signals, excluded_span_ids=excluded)
