"""
Local smoke test for Azure Document Translation using managed-identity-style auth
(via az login on dev machines). Mirrors what the agentcore component will do.

Prereqs:
  - pip install azure-identity azure-ai-translation-document
  - az login --tenant <YOUR-TENANT-ID>
  - The Translator's system-assigned MI has Storage Blob Data Contributor on the
    storage account `reastranslation`.
  - Your user has Cognitive Services User on the Translator (or its RG).
  - File `sample-fr.txt` already uploaded to the `rasource` container.
  - `sample-en.txt` does NOT yet exist in the `rastranslated` container.
"""
import os
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.translation.document import (
    DocumentTranslationClient,
    DocumentTranslationInput,
    TranslationTarget,
)

# ---- Config (pre-filled with your values) ----
TRANSLATOR_ENDPOINT = "https://micoretranslation.cognitiveservices.azure.com/"
STORAGE_ACCOUNT  = "rastranslation"
SOURCE_CONTAINER = "input"
TARGET_CONTAINER = "output"
SOURCE_BLOB      = "fr_file.txt"
TARGET_BLOB      = "sample-en.txt"
TARGET_LANGUAGE  = "en"
SOURCE_LANGUAGE  = None  # None = auto-detect


def main() -> int:
    if "<YOUR-TRANSLATOR-NAME>" in TRANSLATOR_ENDPOINT:
        print(
            "ERROR: Set the AZURE_DOCUMENT_TRANSLATION_ENDPOINT env var "
            "or edit TRANSLATOR_ENDPOINT in the script.",
            file=sys.stderr,
        )
        return 1

    source_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{SOURCE_CONTAINER}/{SOURCE_BLOB}"
    target_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{TARGET_CONTAINER}/{TARGET_BLOB}"

    print(f"Endpoint:        {TRANSLATOR_ENDPOINT}")
    print(f"Source URL:      {source_url}")
    print(f"Target URL:      {target_url}")
    print(f"Source language: {SOURCE_LANGUAGE or '(auto-detect)'}")
    print(f"Target language: {TARGET_LANGUAGE}")
    print()

    # Same credential chain as the agentcore backend uses for blob/search
    credential = DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_interactive_browser_credential=True,
    )
    client = DocumentTranslationClient(TRANSLATOR_ENDPOINT, credential)

    target_kwargs = {"target_url": target_url, "language": TARGET_LANGUAGE}
    input_kwargs = {
        "source_url": source_url,
        "storage_type": "File",  # critical: single-file mode (not container batch)
        "targets": [TranslationTarget(**target_kwargs)],
    }
    if SOURCE_LANGUAGE:
        input_kwargs["source_language"] = SOURCE_LANGUAGE

    inputs = [DocumentTranslationInput(**input_kwargs)]

    print("Submitting translation job...")
    try:
        poller = client.begin_translation(inputs=inputs)
    except Exception as e:
        print(f"FAILED to submit: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    job_id = getattr(poller.details, "id", "(unknown)")
    print(f"Job ID: {job_id}")
    print("Polling for completion (this typically takes 30-90 sec for one small file)...")
    print()

    try:
        result = poller.result()  # blocks until done
    except Exception as e:
        print(f"FAILED while polling: {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    # Per-document results
    print("--- Per-document results ---")
    any_failed = False
    for doc in result:
        print(f"  id:           {doc.id}")
        print(f"  status:       {doc.status}")
        print(f"  source:       {getattr(doc, 'source_document_url', '?')}")
        print(f"  translated:   {getattr(doc, 'translated_document_url', '?')}")
        print(f"  to language:  {getattr(doc, 'translated_to', '?')}")
        print(f"  chars:        {getattr(doc, 'characters_charged', '?')}")
        if getattr(doc, "error", None):
            any_failed = True
            err = doc.error
            code = getattr(err, "code", "?")
            msg = getattr(err, "message", str(err))
            print(f"  ERROR:        [{code}] {msg}")
        print()

    # Final summary
    details = poller.details
    print("--- Final summary ---")
    print(f"  Job status:  {getattr(details, 'status', '?')}")
    print(f"  Total:       {getattr(details, 'documents_total_count', '?')}")
    print(f"  Succeeded:   {getattr(details, 'documents_succeeded_count', '?')}")
    print(f"  Failed:      {getattr(details, 'documents_failed_count', '?')}")
    print(f"  In progress: {getattr(details, 'documents_in_progress_count', '?')}")

    return 0 if not any_failed else 4


if __name__ == "__main__":
    sys.exit(main())
