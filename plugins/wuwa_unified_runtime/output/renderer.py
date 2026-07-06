from __future__ import annotations

from plugins.wuwa_unified_runtime.contracts import CapabilityResult, RenderedOutput, ReviewResult


def render_reviewed_output(
    result: CapabilityResult,
    review: ReviewResult,
) -> RenderedOutput:
    text = review.safe_text or result.body or result.summary or result.title
    return RenderedOutput(
        request_id=result.request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
        size_estimate=len(text),
        risk_level=review.risk_level,
        privacy_level=review.privacy_level,
    )
