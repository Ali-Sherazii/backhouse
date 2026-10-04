"""OCR for page renders: Docling first, PaddleOCR as fallback.

Both engines are heavy, imported lazily and cached per worker process. If neither
is installed `ocr_png` returns None and the caller carries on with the text layer.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class OcrResult:
    words: list[tuple[str, list[float]]]  # (text, normalised bbox x0,y0,x1,y1)
    markdown: str
    engine: str

    @property
    def plain_text(self) -> str:
        return " ".join(t for t, _ in self.words)


@lru_cache
def _docling_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    opts.ocr_options.force_full_page_ocr = True
    return DocumentConverter(
        allowed_formats=[InputFormat.IMAGE],
        format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts)},
    )


def _ocr_docling(png: bytes) -> OcrResult:
    from docling.datamodel.base_models import DocumentStream
    from docling_core.types.doc import ContentLayer, TableItem

    res = _docling_converter().convert(DocumentStream(name="page.png", stream=io.BytesIO(png)))
    doc = res.document
    page = next(iter(doc.pages.values()))
    width, height = page.size.width, page.size.height

    def norm(bbox) -> list[float]:
        b = bbox.to_top_left_origin(page_height=height)
        return [round(b.l / width, 5), round(b.t / height, 5), round(b.r / width, 5), round(b.b / height, 5)]

    words: list[tuple[str, list[float]]] = []
    # Include page furniture (headers/footers): invoices put payment terms and bank details there.
    for item, _level in doc.iterate_items(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}):
        if isinstance(item, TableItem):
            for cell in item.data.table_cells:
                if cell.text and cell.text.strip() and cell.bbox is not None:
                    words.append((cell.text.strip(), norm(cell.bbox)))
        elif getattr(item, "text", None) and item.prov:
            for prov in item.prov:
                words.append((item.text.strip(), norm(prov.bbox)))
    return OcrResult(words=words, markdown=doc.export_to_markdown(), engine="docling")


@lru_cache
def _paddle_engine():
    from paddleocr import PaddleOCR

    return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)


def _ocr_paddle(png: bytes) -> OcrResult:
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size
    result = _paddle_engine().ocr(np.array(img), cls=True)
    words: list[tuple[str, list[float]]] = []
    for box, (text, _conf) in (result[0] or []) if result else []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        words.append((text.strip(), [round(min(xs) / w, 5), round(min(ys) / h, 5), round(max(xs) / w, 5), round(max(ys) / h, 5)]))
    words.sort(key=lambda wb: (round(wb[1][1], 2), wb[1][0]))
    return OcrResult(words=words, markdown="\n".join(t for t, _ in words), engine="paddle")


def available_engines() -> list[str]:
    configured = get_settings().ocr_engine
    if configured == "none":
        return []
    order = ["docling", "paddle"] if configured != "paddle" else ["paddle", "docling"]
    return order


def ocr_png(png: bytes) -> OcrResult | None:
    for engine in available_engines():
        try:
            return _ocr_docling(png) if engine == "docling" else _ocr_paddle(png)
        except ImportError:
            log.info("OCR engine %s not installed, trying next", engine)
        except Exception:
            log.exception("OCR engine %s failed, trying next", engine)
    return None
