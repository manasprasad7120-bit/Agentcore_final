"""Classify chat-uploaded files into image / document / unsupported.

Used by Message.model_post_init to dispatch attachments to the correct
schema (Image vs FileAttachment) so non-image files no longer get wrapped
as fake image_url blocks and silently dropped by the LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

IMAGE_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff",
})

EXTRACTABLE_EXTS: frozenset[str] = frozenset({
    # Documents
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".xlsm",
    # Text / markup
    ".txt", ".md", ".mdx", ".csv", ".html", ".htm", ".tex",
    ".json", ".yaml", ".yml", ".xml",
    # Code
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp", ".c", ".cs",
    ".h", ".hpp", ".go", ".rs", ".sh", ".sql", ".rb", ".php", ".css",
})

FileKind = Literal["image", "document", "unsupported"]


def _ext(path_or_name) -> str:
    if path_or_name is None:
        return ""
    s = path_or_name.path if hasattr(path_or_name, "path") else str(path_or_name)
    return Path(s).suffix.lower()


def classify(path_or_name) -> FileKind:
    """Return the attachment kind for a path, filename, or Image-like object."""
    ext = _ext(path_or_name)
    if ext in IMAGE_EXTS:
        return "image"
    if ext in EXTRACTABLE_EXTS:
        return "document"
    return "unsupported"


def supported_extensions() -> list[str]:
    """Flat list of every extension we accept, sans leading dot — for UI / API responses."""
    return sorted({e.lstrip(".") for e in IMAGE_EXTS | EXTRACTABLE_EXTS})
