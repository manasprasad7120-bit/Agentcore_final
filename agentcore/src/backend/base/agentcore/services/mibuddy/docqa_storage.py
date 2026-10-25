"""Dedicated storage for all MiBuddy operations.

Uses a separate Azure Blob container (MIBUDDY_BLOB_CONTAINER) with organized
folder structure per user:

    {container}/
    ├── {user_id}/
    │   ├── uploads/              ← documents uploaded by user in chat
    │   │   ├── report.pdf
    │   │   └── data.xlsx
    │   ├── generated-images/     ← AI-generated images (DALL-E, Nano Banana)
    │   │   ├── 2026-04-08_ai_generated_abc123.png
    │   │   └── 2026-04-08_ai_generated_def456.png
    │   └── chat-images/          ← images uploaded in chat (for vision)
    │       ├── screenshot.png
    │       └── photo.jpg

Falls back to the main storage service if MIBUDDY_BLOB_CONTAINER is not configured.
"""

from __future__ import annotations

import os
import logging
from enum import Enum

logger = logging.getLogger(__name__)

_container_client = None


class FileCategory(str, Enum):
    """Folder categories within the MiBuddy container."""
    UPLOADS = "uploads"                    # documents uploaded for Q&A
    GENERATED_IMAGES = "generated-images"  # AI-generated images
    CHAT_IMAGES = "chat-images"            # images uploaded for vision


def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


async def _get_container():
    """Get or create the dedicated MiBuddy blob container client (singleton)."""
    global _container_client

    if _container_client is not None:
        return _container_client

    settings = _get_settings()
    container_name = settings.mibuddy_blob_container

    if not container_name:
        return None

    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "").strip().strip("'\"")
    storage_type = (os.environ.get("STORAGE_TYPE", "local")).lower()

    if storage_type != "azure" or not account_url:
        return None

    try:
        from azure.storage.blob.aio import BlobServiceClient
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_interactive_browser_credential=True,
        )
        blob_service = BlobServiceClient(account_url=account_url, credential=credential)
        container = blob_service.get_container_client(container_name)

        try:
            await container.get_container_properties()
        except Exception:
            await container.create_container()
            logger.info(f"[MiBuddy] Created blob container: {container_name}")

        _container_client = container
        return _container_client

    except Exception as e:
        logger.warning(f"[MiBuddy] Failed to init container '{container_name}': {e}")
        return None


def _build_blob_path(user_id: str, category: FileCategory, file_name: str) -> str:
    """Build blob path: {user_id}/{category}/{file_name}"""
    return f"{user_id}/{category.value}/{file_name}"


async def get_public_blob_url(blob_path: str) -> str | None:
    """Return the raw Azure Blob Storage URL for a given path.

    Matches MiBuddy's behavior — returns the direct public-access URL,
    suitable for sharing outside the app. Requires the blob container to
    have "Blob" public access level configured in Azure Portal.

    Format: https://<account>.blob.core.windows.net/<container>/<blob_path>

    Returns None if blob storage isn't configured.
    """
    container = await _get_container()
    if container is None:
        return None
    try:
        blob_client = container.get_blob_client(blob_path)
        return blob_client.url
    except Exception as e:
        logger.debug(f"[MiBuddy] Failed to build public blob URL: {e}")
        return None


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

async def save_file(
    user_id: str,
    file_name: str,
    data: bytes,
    category: FileCategory = FileCategory.UPLOADS,
) -> str:
    """Save a file to the MiBuddy container.

    Args:
        user_id: User UUID.
        file_name: File name (e.g. "report.pdf", "ai_generated_abc.png").
        data: File bytes.
        category: Folder category (uploads, generated-images, chat-images).

    Returns:
        Storage path: "{user_id}/{category}/{file_name}"
    """
    container = await _get_container()

    if container:
        blob_path = _build_blob_path(user_id, category, file_name)
        blob_client = container.get_blob_client(blob_path)
        await blob_client.upload_blob(data, overwrite=True)
        logger.info(f"[MiBuddy] Saved {category.value}/{file_name} for user {user_id}")
        return blob_path
    else:
        # Fallback: use main storage with category as subfolder
        from agentcore.services.deps import get_storage_service
        storage = get_storage_service()
        prefixed_name = f"{category.value}/{file_name}"
        await storage.save_file(agent_id=user_id, file_name=prefixed_name, data=data)
        return f"{user_id}/{prefixed_name}"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_file(
    user_id: str,
    file_name: str,
    category: FileCategory = FileCategory.UPLOADS,
) -> bytes:
    """Read a file from the MiBuddy container.

    Args:
        user_id: User UUID.
        file_name: File name.
        category: Folder category.

    Returns:
        File bytes.
    """
    container = await _get_container()

    if container:
        blob_path = _build_blob_path(user_id, category, file_name)
        blob_client = container.get_blob_client(blob_path)
        stream = await blob_client.download_blob()
        return await stream.readall()
    else:
        from agentcore.services.deps import get_storage_service
        storage = get_storage_service()
        prefixed_name = f"{category.value}/{file_name}"
        return await storage.get_file(agent_id=user_id, file_name=prefixed_name)


# ---------------------------------------------------------------------------
# Read by full path (for document extractor — path may come from DB)
# ---------------------------------------------------------------------------

async def get_file_by_path(file_path: str) -> bytes:
    """Read a file using its full storage path.

    Tries MiBuddy container first, then main storage as fallback.
    file_path format: "{user_id}/{category}/{file_name}" or "{user_id}/{file_name}"
    """
    container = await _get_container()

    if container:
        try:
            blob_client = container.get_blob_client(file_path)
            stream = await blob_client.download_blob()
            return await stream.readall()
        except Exception:
            pass

    # Fallback to main storage
    parts = file_path.replace("\\", "/").split("/", 1)
    agent_id = parts[0] if len(parts) > 1 else ""
    file_name = parts[1] if len(parts) > 1 else file_path

    from agentcore.services.deps import get_storage_service
    storage = get_storage_service()
    return await storage.get_file(agent_id=agent_id, file_name=file_name)


# ---------------------------------------------------------------------------
# List files for a user in a category
# ---------------------------------------------------------------------------

async def list_files(
    user_id: str,
    category: FileCategory = FileCategory.GENERATED_IMAGES,
) -> list[str]:
    """List all files for a user in a category.

    Returns list of file names (not full paths).
    """
    container = await _get_container()
    if not container:
        return []

    prefix = f"{user_id}/{category.value}/"
    names = []
    async for blob in container.list_blobs(name_starts_with=prefix):
        # blob.name is "{user_id}/{category}/{file_name}"
        name = blob.name[len(prefix):]
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_file(
    user_id: str,
    file_name: str,
    category: FileCategory = FileCategory.UPLOADS,
) -> None:
    """Delete a file from the MiBuddy container."""
    container = await _get_container()
    if container:
        blob_path = _build_blob_path(user_id, category, file_name)
        blob_client = container.get_blob_client(blob_path)
        try:
            await blob_client.delete_blob()
            logger.info(f"[MiBuddy] Deleted {blob_path}")
        except Exception as e:
            logger.warning(f"[MiBuddy] Failed to delete {blob_path}: {e}")
