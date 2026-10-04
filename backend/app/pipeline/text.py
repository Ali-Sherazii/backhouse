"""Turn a PDF or image into positioned text spans.

Digital PDFs use the PyMuPDF text layer. Pages with too little text (scans, photos)
are rendered and OCR'd. Every span keeps its bounding box, normalised to 0..1 of
the page, so the review screen can highlight it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pymupdf as fitz

from app.config import get_settings
from app.pipeline import ocr

log = logging.getLogger(__name__)

# Keep text outside the mediabox and don't clip: the guard needs to see it.
TEXT_FLAGS = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_MEDIABOX_CLIP

IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/tiff": "tiff",
}
PDF_TYPES = {"application/pdf"}

# PyMuPDF char_flags bits for how glyphs are painted.
CHAR_FILLED = 16
CHAR_STROKED = 32


@dataclass
class Layout:
    pages: list[dict]  # [{width, height}] in points (PDF) or pixels (image)
    spans: list[dict]  # see _span()
    text_source: str  # text_layer | ocr | mixed
    ocr_text: dict[int, str] = field(default_factory=dict)  # page -> OCR markdown

    def to_json(self) -> dict:
        return {"pages": self.pages, "spans": self.spans, "text_source": self.text_source}


def open_document(data: bytes, content_type: str) -> fitz.Document:
    if content_type in PDF_TYPES:
        return fitz.open(stream=data, filetype="pdf")
    if content_type in IMAGE_TYPES:
        img = fitz.open(stream=data, filetype=IMAGE_TYPES[content_type])
        # Convert to a one-page PDF so every downstream step sees the same API.
        return fitz.open("pdf", img.convert_to_pdf())
    raise ValueError(f"Unsupported content type {content_type}")


def guess_content_type(filename: str, declared: str | None) -> str:
    if declared in PDF_TYPES or declared in IMAGE_TYPES:
        return "image/jpeg" if declared == "image/jpg" else declared
    name = filename.lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    for ctype, ext in IMAGE_TYPES.items():
        if name.endswith("." + ext) or (ext == "jpg" and name.endswith(".jpeg")) or (ext == "tiff" and name.endswith(".tif")):
            return ctype
    raise ValueError(f"Unsupported file type: {filename}")


def render_page_png(page: fitz.Page, dpi: int | None = None) -> bytes:
    pix = page.get_pixmap(dpi=dpi or get_settings().page_render_dpi, alpha=False)
    return pix.tobytes("png")


def _hex(color: int) -> str:
    return f"#{color:06x}"


def _norm_bbox(bbox, width: float, height: float) -> list[float]:
    x0, y0, x1, y1 = bbox
    return [round(x0 / width, 5), round(y0 / height, 5), round(x1 / width, 5), round(y1 / height, 5)]


def text_layer_spans(doc: fitz.Document) -> list[dict]:
    spans: list[dict] = []
    for pno, page in enumerate(doc):
        rect = page.rect
        data = page.get_text("dict", flags=TEXT_FLAGS, clip=fitz.INFINITE_RECT())
        for block in data["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    if not s["text"].strip():
                        continue
                    spans.append(
                        {
                            "id": len(spans),
                            "page": pno,
                            "text": s["text"].strip(),
                            "bbox": _norm_bbox(s["bbox"], rect.width, rect.height),
                            "pt": [round(v, 2) for v in s["bbox"]],
                            "size": round(s["size"], 2),
                            "color": _hex(s["color"]),
                            "alpha": s.get("alpha", 255),
                            "painted": bool(s.get("char_flags", CHAR_FILLED) & (CHAR_FILLED | CHAR_STROKED)),
                            "font": s["font"],
                            "source": "text_layer",
                        }
                    )
    return spans


def _meaningful_chars(spans: list[dict], page: int) -> int:
    return sum(len(s["text"].replace(" ", "")) for s in spans if s["page"] == page)


def extract_layout(doc: fitz.Document) -> Layout:
    s = get_settings()
    pages = [{"width": round(p.rect.width, 2), "height": round(p.rect.height, 2)} for p in doc]
    layer = text_layer_spans(doc)
    spans: list[dict] = []
    ocr_text: dict[int, str] = {}
    sources = set()
    for pno, page in enumerate(doc):
        if _meaningful_chars(layer, pno) >= s.text_layer_min_chars:
            spans.extend(sp for sp in layer if sp["page"] == pno)
            sources.add("text_layer")
            continue
        result = ocr.ocr_png(render_page_png(page, dpi=200))
        if result is None:
            # No OCR engine available: keep whatever thin text layer exists.
            page_layer = [sp for sp in layer if sp["page"] == pno]
            spans.extend(page_layer)
            sources.add("text_layer" if page_layer else "none")
            continue
        ocr_text[pno] = result.markdown
        for text, bbox in result.words:
            spans.append(
                {
                    "id": 0,
                    "page": pno,
                    "text": text,
                    "bbox": bbox,
                    "pt": [round(bbox[0] * page.rect.width, 2), round(bbox[1] * page.rect.height, 2),
                           round(bbox[2] * page.rect.width, 2), round(bbox[3] * page.rect.height, 2)],
                    "size": None,
                    "color": None,
                    "alpha": 255,
                    "painted": True,
                    "font": None,
                    "source": "ocr",
                }
            )
        sources.add("ocr")
    for i, sp in enumerate(spans):
        sp["id"] = i
    text_source = "mixed" if len(sources) > 1 else (sources.pop() if sources else "text_layer")
    return Layout(pages=pages, spans=spans, text_source=text_source, ocr_text=ocr_text)


def spans_to_text(spans: list[dict], exclude: set[int] | None = None) -> str:
    """Rebuild reading-order text: group spans into rows by vertical centre, then sort by x."""
    exclude = exclude or set()
    out_pages: list[str] = []
    for page in sorted({s["page"] for s in spans}):
        rows: list[list[dict]] = []
        page_spans = sorted(
            (s for s in spans if s["page"] == page and s["id"] not in exclude),
            key=lambda s: ((s["bbox"][1] + s["bbox"][3]) / 2, s["bbox"][0]),
        )
        for sp in page_spans:
            cy = (sp["bbox"][1] + sp["bbox"][3]) / 2
            h = max(sp["bbox"][3] - sp["bbox"][1], 0.004)
            if rows:
                last = rows[-1][0]
                lcy = (last["bbox"][1] + last["bbox"][3]) / 2
                if abs(cy - lcy) < h * 0.5:
                    rows[-1].append(sp)
                    continue
            rows.append([sp])
        # " | " between cells keeps table columns apart, e.g. "Roma tomatoes 25 lb case | 5 | case | $29.10".
        lines = [" | ".join(s["text"] for s in sorted(row, key=lambda s: s["bbox"][0])) for row in rows]
        out_pages.append("\n".join(lines))
    return "\n\n--- page break ---\n\n".join(out_pages)


def page_images(doc: fitz.Document) -> list[bytes]:
    return [render_page_png(p) for p in doc]
