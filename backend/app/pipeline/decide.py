"""Auto-approve only when nothing is uncertain. Everything else goes to a human."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import DocStatus
from app.pipeline.validate import BLOCKING, CheckResult
from app.schemas import REQUIRED_FIELDS


@dataclass
class Decision:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def auto_approved(self) -> bool:
        return self.status == DocStatus.APPROVED


def decide(
    *,
    guard_flagged: bool,
    checks: list[CheckResult],
    data: dict,
    confidence: dict,
    threshold: float,
) -> Decision:
    reasons: list[str] = []
    if guard_flagged:
        reasons.append("Injection guard flagged the document")
    for c in checks:
        if c.severity == BLOCKING and not c.passed:
            reasons.append(f"Check failed: {c.name}: {c.detail}")
    for name in REQUIRED_FIELDS:
        if data.get(name) in (None, ""):
            reasons.append(f"Missing required field: {name}")
        elif confidence.get(name, 0.0) < threshold:
            reasons.append(f"Low confidence on {name} ({confidence.get(name, 0.0):.2f} < {threshold:.2f})")
    return Decision(DocStatus.NEEDS_REVIEW if reasons else DocStatus.APPROVED, reasons)
