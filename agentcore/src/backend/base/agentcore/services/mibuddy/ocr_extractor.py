"""OCR helper for scanned-PDF pages in the MiBuddy Doc Q&A pipeline.

Wraps Azure Document Intelligence's `prebuilt-read` model. The caller decides
WHICH pages need OCR (by doing native extraction first); we only handle the
Azure SDK call and the result→{page_number: text} mapping.

Matches MiBuddy's OCR service choice (`azure-ai-formrecognizer` +
`begin_analyze_document("prebuilt-read", ...)`) but scopes the call with the
`pages=` parameter so we only pay for the pages that actually need OCR.

Graceful degradation: if ADI credentials are not configured the helper returns
an empty mapping and logs a warning. Callers continue with whatever native
text they already extracted.
"""

from __future__ import annotations

import asyncio

from loguru import logger

# Module-level singleton — DocumentAnalysisClient is thread-safe and reuses the
# underlying HTTP connection across calls.
_client = None
_client_init_failed = False


def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


def _get_client():
    """Lazily construct the Azure Document Intelligence client.

    Returns None when ADI env vars are missing — the caller should treat that
    as "OCR not configured" and continue with native text only.
    """
    global _client, _client_init_failed

    if _client is not None:
        return _client
    if _client_init_failed:
        return None

    settings = _get_settings()
    endpoint = (settings.azure_document_intelligence_endpoint or "").strip()
    key = (settings.azure_document_intelligence_key or "").strip()

    if not endpoint or not key:
        # Mark as failed so repeated callers don't keep re-checking. Harmless
        # because the dev just needs to restart after setting the env vars.
        _client_init_failed = True
        logger.warning(
            "[OCR] Azure Document Intelligence not configured "
            "(AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT / _KEY). "
            "Scanned PDF pages will be skipped."
        )
        return None

    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential

        _client = DocumentAnalysisClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )
        logger.info("[OCR] Azure Document Intelligence client initialized")
        return _client
    except Exception as exc:  # noqa: BLE001
        _client_init_failed = True
        logger.warning(f"[OCR] Failed to init Document Intelligence client: {exc}")
        return None


def _pages_csv(pages: list[int]) -> str:
    """Format 1-based page numbers as the CSV string ADI expects ("1,3,5")."""
    return ",".join(str(p) for p in pages)


def _run_ocr_sync(pdf_bytes: bytes, pages: list[int]) -> dict[int, str]:
    """Synchronous Azure SDK call — intended to be wrapped with asyncio.to_thread."""
    client = _get_client()
    if client is None:
        return {}

    pages_param = _pages_csv(pages)
    try:
        poller = client.begin_analyze_document(
            "prebuilt-read", pdf_bytes, pages=pages_param,
        )
        result = poller.result()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[OCR] ADI call failed for pages={pages_param}: {exc}"
        )
        return {}

    ocr_by_page: dict[int, str] = {}
    for page in getattr(result, "pages", []) or []:
        page_num = getattr(page, "page_number", None)
        if not page_num:
            continue
        lines = getattr(page, "lines", []) or []
        text = "\n".join(getattr(line, "content", "") for line in lines).strip()
        if text:
            ocr_by_page[int(page_num)] = text
    return ocr_by_page


async def ocr_pdf_pages(pdf_bytes: bytes, pages: list[int]) -> dict[int, str]:
    """Run Azure Document Intelligence `prebuilt-read` on the given 1-based pages.

    Returns a `{page_number: text}` mapping. Pages that returned no lines are
    omitted (not keys with empty strings). Returns `{}` if:
      - no pages were requested
      - ADI isn't configured
      - the Azure call fails

    The SDK is synchronous, so we offload to a thread to avoid blocking the
    FastAPI event loop.
    """
    if not pages:
        return {}
    return await asyncio.to_thread(_run_ocr_sync, pdf_bytes, sorted(set(pages)))


def is_ocr_configured() -> bool:
    """Cheap check for callers that want to short-circuit without calling OCR."""
    return _get_client() is not None


def _run_office_ocr_sync(file_bytes: bytes) -> str:
    """Synchronous whole-file OCR for DOCX / PPTX — wrap with asyncio.to_thread.

    ADI's `prebuilt-read` natively accepts .docx and .pptx — it unpacks the
    zip, pulls native text from the XML, AND runs OCR on any embedded images
    in one call. We use this as a fallback when python-docx / python-pptx
    returned no native text (rare edge case: files that contain only
    embedded images, e.g. a scanned page pasted into Word).
    """
    client = _get_client()
    if client is None:
        return ""

    try:
        poller = client.begin_analyze_document("prebuilt-read", file_bytes)
        result = poller.result()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[OCR] ADI office-file call failed: {exc}")
        return ""

    parts: list[str] = []
    for page in getattr(result, "pages", []) or []:
        for line in getattr(page, "lines", []) or []:
            content = getattr(line, "content", "")
            if content:
                parts.append(content)
    return "\n".join(parts).strip()


async def ocr_office_bytes(file_bytes: bytes) -> str:
    """OCR a whole DOCX or PPTX via Azure Document Intelligence.

    Matches MiBuddy's wider OCR net — when python-docx / python-pptx returns
    no text (e.g. the document contains only embedded images), ADI can still
    recover the text. Returns `""` if ADI isn't configured or the call fails.
    """
    return await asyncio.to_thread(_run_office_ocr_sync, file_bytes)
