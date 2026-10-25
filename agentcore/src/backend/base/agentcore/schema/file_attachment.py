"""FileAttachment — non-image chat attachments inlined as text in the LLM prompt.

Mirrors the lazy-resolve pattern of `Image`: `resolve()` is awaited once
upstream (e.g. by ChatInput.message_response or Message.resolve_attachments),
which fetches bytes from storage, runs them through the document extractor,
caches the text, and applies a char cap. `to_content_dict()` is then a
synchronous read of the cache, suitable for `to_lc_message`.

Extraction errors (scanned PDF, corrupt file, storage miss, timeout) do not
raise out of resolve — they are stored in `_error` and surfaced to the LLM
as `<file name='X' error='reason'/>` so the flow keeps running.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, PrivateAttr

# Read env vars inline rather than importing from agentcore.base.data.utils:
# that module pulls in BaseFileNode → field_typing → schema.dataframe, which
# would create a circular import (schema/__init__ → dataframe → message →
# file_attachment → base.data.utils → ... → schema.dataframe).
MAX_INLINE_FILE_CHARS = int(os.getenv("AGENTCORE_MAX_INLINE_FILE_CHARS", "50000"))
FILE_EXTRACTION_TIMEOUT_SEC = int(os.getenv("AGENTCORE_FILE_EXTRACTION_TIMEOUT", "30"))

# Map a code-file extension to a markdown fenced-block language tag so the
# LLM gets a hint about syntax. Non-code text formats fall through to "".
_CODE_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx", ".java": "java",
    ".cpp": "cpp", ".c": "c", ".cs": "csharp",
    ".h": "c", ".hpp": "cpp",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".sh": "bash", ".sql": "sql", ".css": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".xml": "xml",
    ".html": "html", ".htm": "html", ".md": "markdown", ".mdx": "markdown",
}


class FileAttachment(BaseModel):
    """Lazy-resolved text attachment for the LLM.

    `path` is a storage-relative key like "{agent_id}/{filename}".
    """

    path: str
    # Image-shaped duck-typing: conversation persistence checks
    # `hasattr(file, "url")` to identify attachment objects vs raw strings.
    # Always None for documents — kept so the DB layer treats us like Image.
    url: str | None = None

    _text_cache: str | None = PrivateAttr(default=None)
    _truncated: bool = PrivateAttr(default=False)
    _error: str | None = PrivateAttr(default=None)
    _resolved: bool = PrivateAttr(default=False)

    @property
    def file_name(self) -> str:
        return Path(self.path).name

    @property
    def file_ext(self) -> str:
        return Path(self.path).suffix.lower()

    async def resolve(self) -> None:
        """Fetch bytes, extract text, cache. Idempotent."""
        if self._resolved:
            return
        self._resolved = True

        # Local imports keep the schema package cheap to import and avoid
        # circulars with the storage / extractor services.
        from agentcore.services.mibuddy.document_extractor import (
            ScannedPdfError,
            extract_text_no_ocr,
        )

        try:
            text = await asyncio.wait_for(
                extract_text_no_ocr(self.path),
                timeout=FILE_EXTRACTION_TIMEOUT_SEC,
            )
        except ScannedPdfError as e:
            logger.warning(f"[FileAttachment] scanned PDF, no OCR: {self.path}: {e}")
            self._error = "scanned-pdf-not-supported"
            return
        except asyncio.TimeoutError:
            logger.error(f"[FileAttachment] extraction timeout: {self.path}")
            self._error = "extraction-timeout"
            return
        except FileNotFoundError:
            logger.error(f"[FileAttachment] file not found in storage: {self.path}")
            self._error = "storage-unavailable"
            return
        except ValueError as e:
            # Unsupported ext caught by document_extractor — should not happen
            # because the classifier already filtered, but defend anyway.
            logger.warning(f"[FileAttachment] unsupported: {self.path}: {e}")
            self._error = "unsupported-file-type"
            return
        except Exception as e:  # noqa: BLE001
            logger.error(f"[FileAttachment] extraction failed: {self.path}: {e}")
            self._error = "extraction-failed"
            return

        if not text or not text.strip():
            self._error = "empty"
            return

        if len(text) > MAX_INLINE_FILE_CHARS:
            text = text[:MAX_INLINE_FILE_CHARS]
            self._truncated = True

        self._text_cache = text

    def to_content_dict(self) -> dict[str, Any]:
        """Build a LangChain `text` content block for `HumanMessage.content`.

        Must be called only after `resolve()` has completed.
        """
        if not self._resolved:
            # Defensive: surface as error rather than raise — matches the
            # philosophy of degrading gracefully so the build never crashes.
            return {
                "type": "text",
                "text": f"<file name='{self.file_name}' error='not-resolved'/>",
            }

        if self._error:
            return {
                "type": "text",
                "text": f"<file name='{self.file_name}' error='{self._error}'/>",
            }

        body = self._text_cache or ""
        lang = _CODE_LANG.get(self.file_ext)
        if lang:
            body = f"```{lang}\n{body}\n```"

        suffix = "\n[truncated]" if self._truncated else ""
        text = (
            f"<file name='{self.file_name}' type='{self.file_ext}'>\n"
            f"{body}{suffix}\n"
            f"</file>"
        )
        return {"type": "text", "text": text}
