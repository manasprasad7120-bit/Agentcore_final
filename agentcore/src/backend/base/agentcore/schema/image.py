import base64
import mimetypes
from pathlib import Path

from PIL import Image as PILImage
from pydantic import BaseModel, PrivateAttr

from agentcore.services.deps import get_storage_service

IMAGE_ENDPOINT = "/files/images/"

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".svg"}


def is_image_file(file_path) -> bool:
    # Already an Image object
    if isinstance(file_path, BaseModel) and hasattr(file_path, "path"):
        path_str = file_path.path or ""
        return Path(path_str).suffix.lower() in _IMAGE_EXTENSIONS

    # Try opening with PIL (works for local files)
    if isinstance(file_path, (str, Path)):
        try:
            with PILImage.open(str(file_path)) as img:
                img.verify()
            return True
        except (OSError, SyntaxError):
            pass

    # Fallback: check by file extension (for remote/Azure storage paths)
    try:
        path_str = str(file_path)
        ext = Path(path_str).suffix.lower()
        return ext in _IMAGE_EXTENSIONS
    except Exception:
        return False


def get_file_paths(files: list[str]):
    storage_service = get_storage_service()
    file_paths = []
    for file in files:
        file_path = Path(file.path) if hasattr(file, "path") and file.path else Path(file)
        agent_id, file_name = str(file_path.parent), file_path.name
        file_paths.append(storage_service.build_full_path(agent_id=agent_id, file_name=file_name))
    return file_paths


async def get_files(
    file_paths: list[str],
    *,
    convert_to_base64: bool = False,
):
    storage_service = get_storage_service()
    file_objects: list[str | bytes] = []
    for file in file_paths:
        file_path = Path(file)
        agent_id, file_name = str(file_path.parent), file_path.name
        file_object = await storage_service.get_file(agent_id=agent_id, file_name=file_name)
        if convert_to_base64:
            file_base64 = base64.b64encode(file_object).decode("utf-8")
            file_objects.append(file_base64)
        else:
            file_objects.append(file_object)
    return file_objects


class Image(BaseModel):
    path: str | None = None
    url: str | None = None
    # Pre-resolved base64 data — populated by resolve() so that
    # to_content_dict() can work synchronously without hitting storage.
    _base64_cache: str | None = PrivateAttr(default=None)

    async def resolve(self) -> None:
        """Fetch the image from storage and cache its base64 representation."""
        if self._base64_cache is not None:
            return
        if not self.path:
            return
        files = await get_files([self.path], convert_to_base64=True)
        if files:
            self._base64_cache = files[0]

    def to_base64(self) -> str:
        if self._base64_cache is not None:
            return self._base64_cache
        # Fallback for local files only
        if self.path:
            path = Path(self.path)
            if path.exists() and path.is_file():
                with path.open("rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        msg = f"Image not resolved. Call await image.resolve() first. path={self.path}"
        raise ValueError(msg)

    def to_content_dict(self) -> dict:
        path_str = self.path or ""
        mime_type = mimetypes.guess_type(path_str)[0] or "image/png"
        base64_data = self.to_base64()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
        }

    def get_url(self) -> str:
        return f"{IMAGE_ENDPOINT}{self.path}"
