"""Celery tasks: the document pipeline and the export hand-off to n8n."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone

import httpx
from celery.exceptions import Retry

from app import services, storage
from app.celery_app import EXPORT_TASK, PROCESS_TASK, celery_app
from app.config import get_settings
from app.db import SessionLocal
from app.models import Check, DocStatus, Document, Extraction, GuardResult
from app.pipeline import extract, guard, locate, ocr, text
from app.pipeline.decide import decide
from app.pipeline.validate import CheckResult
from app.schemas import InvoiceFields

log = logging.getLogger(__name__)


def _ocr_plain(png: bytes) -> str | None:
    result = ocr.ocr_png(png)
    return result.plain_text if result else None


def llm_text(layout: text.Layout, excluded: set[int]) -> str:
    """Text for the extractor: OCR markdown for scanned pages, rebuilt rows for text-layer pages."""
    parts = []
    for pno in range(len(layout.pages)):
        if pno in layout.ocr_text:
            parts.append(layout.ocr_text[pno])
        else:
            parts.append(text.spans_to_text([s for s in layout.spans if s["page"] == pno], exclude=excluded))
    return "\n\n--- page break ---\n\n".join(p for p in parts if p.strip())


def _guard_summary(outcome: guard.GuardOutcome) -> dict:
    return {
        "flagged": outcome.flagged,
        "strong": [s["detector"] for s in outcome.signals if s["strength"] == guard.STRONG],
        "weak": [s["detector"] for s in outcome.signals if s["strength"] == guard.WEAK],
    }


@celery_app.task(name=PROCESS_TASK, bind=True, max_retries=3)
def process_document(self, document_id: int) -> str | None:
    s = get_settings()
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            log.warning("Document %s not found", document_id)
            return None
        if doc.status not in (DocStatus.QUEUED, DocStatus.PROCESSING, DocStatus.FAILED):
            return doc.status
        started = time.monotonic()
        doc.status = DocStatus.PROCESSING
        doc.error = None
        if self.request.retries == 0:
            services.audit(db, doc, "processing_started")
        db.commit()

        # 1. Load
        raw = storage.get_bytes(doc.minio_key)
        doc.sha256 = hashlib.sha256(raw).hexdigest()
        pdf = text.open_document(raw, doc.content_type)

        # 2. Text with positions, and page renders for the review screen
        layout = text.extract_layout(pdf)
        for pno, png in enumerate(text.page_images(pdf)):
            storage.put_bytes(storage.page_key(doc.id, pno), png, "image/png")
        doc.page_count = len(layout.pages)
        doc.text_source = layout.text_source

        # 3. Guard, before any LLM call
        has_layer = any(sp["source"] == "text_layer" for sp in layout.spans)
        outcome = guard.run_guard(
            pdf,
            layout.spans,
            ocr_fn=_ocr_plain if (s.guard_ocr_diff and has_layer and s.ocr_engine != "none") else None,
            scorer=guard.prompt_guard_scores,
        )
        for sp in layout.spans:
            if sp["id"] in outcome.excluded_span_ids:
                sp["excluded"] = True
        doc.layout = layout.to_json()
        if doc.guard_result is None:
            doc.guard_result = GuardResult(flagged=outcome.flagged, signals=outcome.signals)
        else:
            doc.guard_result.flagged, doc.guard_result.signals = outcome.flagged, outcome.signals
        db.commit()

        # 4. Extract (from sanitised text, wrapped in spotlighting delimiters)
        clean_text = llm_text(layout, outcome.excluded_span_ids)
        extraction_error = None
        try:
            result = extract.extract_invoice(clean_text, document_id=doc.id, guard_summary=_guard_summary(outcome))
        except extract.LLMUnavailable as exc:
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
        except extract.ExtractionError as exc:
            result, extraction_error = None, str(exc)

        visible_spans = [sp for sp in layout.spans if not sp.get("excluded")]
        if result is not None:
            data = result.data
            confidence, boxes, ungrounded = locate.ground(result.data, result.confidence, visible_spans)
            if locate.fill_missing_discount(data, confidence, boxes, visible_spans):
                confidence["_filled_from_page"] = ["discount"]
        else:
            data, confidence, boxes, ungrounded = InvoiceFields().model_dump(), {}, {}, []

        ext = doc.extraction or Extraction(document_id=doc.id)
        ext.data = data
        ext.field_confidence = {**confidence, "_ungrounded": ungrounded}
        ext.field_boxes = boxes
        ext.model = result.model if result else s.llm_model
        ext.latency_ms = result.latency_ms if result else None
        ext.langfuse_trace_id = result.trace_id if result else None
        doc.extraction = ext

        # 5. Validate
        checks = services.validate_and_store(db, doc, data)
        if extraction_error:
            extra = CheckResult("extraction", False, extraction_error[:500])
            checks.append(extra)
            doc.checks.append(Check(name=extra.name, passed=False, severity=extra.severity, detail=extra.detail))

        # 6. Decide
        decision = decide(
            guard_flagged=outcome.flagged,
            checks=checks,
            data=data,
            confidence=confidence,
            threshold=s.auto_approve_min_confidence,
        )
        doc.processed_at = datetime.now(timezone.utc)
        doc.processing_ms = int((time.monotonic() - started) * 1000)
        services.audit(db, doc, "processed", after={"decision": decision.status, "reasons": decision.reasons})

        # 7. Approval side effects
        if decision.auto_approved:
            services.mark_approved(db, doc, data, user=None, auto=True)
        else:
            doc.status = DocStatus.NEEDS_REVIEW
            db.commit()
        return doc.status
    except Retry:
        raise
    except Exception as exc:
        log.exception("Processing document %s failed", document_id)
        db.rollback()
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status = DocStatus.FAILED
            doc.error = f"{type(exc).__name__}: {exc}"[:2000]
            services.audit(db, doc, "failed", after={"error": doc.error})
            db.commit()
        return DocStatus.FAILED
    finally:
        db.close()


@celery_app.task(name=EXPORT_TASK, bind=True, max_retries=5)
def export_document(self, document_id: int) -> None:
    s = get_settings()
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None or doc.status != DocStatus.APPROVED:
            return
        payload = services.export_payload(db, doc, s.app_public_url)
        try:
            resp = httpx.post(
                s.n8n_export_webhook_url,
                json=payload,
                headers={"X-Backhouse-Secret": s.webhook_secret},
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if self.request.retries >= self.max_retries:
                doc.error = f"Export to n8n failed: {exc}"[:2000]
                services.audit(db, doc, "export_failed", after={"error": doc.error})
                db.commit()
                return
            raise self.retry(exc=exc, countdown=20 * (self.request.retries + 1))
        services.audit(db, doc, "export_requested", after={"webhook": s.n8n_export_webhook_url})
        db.commit()
    finally:
        db.close()
