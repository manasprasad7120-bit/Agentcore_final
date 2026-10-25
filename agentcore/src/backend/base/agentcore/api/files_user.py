import io
import re
import uuid
import zipfile
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import col, select
from sqlalchemy import and_, or_

from agentcore.api.schemas import UserUploadFileResponse
from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.file.model import File as UserFile
from agentcore.services.database.models.knowledge_base.model import KBVisibilityEnum, KnowledgeBase
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.deps import get_settings_service, get_storage_service
from agentcore.services.storage.service import StorageService


router = APIRouter(tags=["Files"], prefix="/files")

# Set the static name of the MCP servers file
MCP_SERVERS_FILE = "_mcp_servers"
SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"
_SECRET_TOKEN_RE = re.compile(
    r"(gsk_[A-Za-z0-9_\-]+|sk-ant-[A-Za-z0-9_\-]+|sk-or-[A-Za-z0-9_\-]+|sk-[A-Za-z0-9_\-]+|xai-[A-Za-z0-9_\-]+|hf_[A-Za-z0-9_\-]+|AIza[0-9A-Za-z_\-]+)"
)


async def _build_file_visibility_filters(session: DbSession, current_user: CurrentActiveUser):
    role = normalize_role(getattr(current_user, "role", "") or "")
    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    org_ids = {r if isinstance(r, uuid.UUID) else r[0] for r in org_rows}
    dept_pairs = await _get_allowed_department_pairs_for_user(session, current_user)
    dept_ids = {dept_id for _, dept_id in dept_pairs}

    def _kb_exists(predicate):
        return (
            select(KnowledgeBase.id)
            .where(KnowledgeBase.id == UserFile.knowledge_base_id, predicate)
            .exists()
        )

    if role == "root":
        root_kb_visible = _kb_exists(
            and_(
                KnowledgeBase.created_by == current_user.id,
                KnowledgeBase.org_id.is_(None),
                KnowledgeBase.dept_id.is_(None),
            )
        )
        return [UserFile.user_id == current_user.id, root_kb_visible]

    predicates: list = []

    if role == "super_admin" and org_ids:
        predicates.append(KnowledgeBase.org_id.in_(list(org_ids)))

    if dept_ids:
        dept_visibility_predicates = [KnowledgeBase.dept_id.in_(list(dept_ids))]
        dept_visibility_predicates.extend(
            [KnowledgeBase.public_dept_ids.contains([str(d)]) for d in dept_ids]
        )
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.DEPARTMENT,
                or_(*dept_visibility_predicates),
            )
        )
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
                KnowledgeBase.created_by == current_user.id,
                KnowledgeBase.dept_id.in_(list(dept_ids)),
            )
        )
        if role == "department_admin":
            predicates.append(
                and_(
                    KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
                    KnowledgeBase.dept_id.in_(list(dept_ids)),
                )
            )

    if org_ids:
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.ORGANIZATION,
                KnowledgeBase.org_id.in_(list(org_ids)),
            )
        )

    if not predicates:
        return [UserFile.user_id == current_user.id, KnowledgeBase.id.is_(None)]
    return [UserFile.user_id == current_user.id, _kb_exists(or_(*predicates))]


async def _resolve_default_scope(session: DbSession, current_user: CurrentActiveUser) -> tuple[uuid.UUID, uuid.UUID]:
    allowed_pairs = await _get_allowed_department_pairs_for_user(session, current_user)
    if not allowed_pairs:
        raise HTTPException(status_code=403, detail="No active department scope found for user")
    return sorted(allowed_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]


async def _get_allowed_department_pairs_for_user(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    role = normalize_role(getattr(current_user, "role", "") or "")

    if role == "root":
        dept_rows = (
            await session.exec(
                select(Department.org_id, Department.id).where(Department.status == "active")
            )
        ).all()
        return {(row[0], row[1]) for row in dept_rows}

    if role == "super_admin":
        org_rows = (
            await session.exec(
                select(UserOrganizationMembership.org_id).where(
                    UserOrganizationMembership.user_id == current_user.id,
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
        ).all()
        org_ids = {r if isinstance(r, uuid.UUID) else r[0] for r in org_rows}
        if not org_ids:
            return set()
        dept_rows = (
            await session.exec(
                select(Department.org_id, Department.id).where(
                    Department.org_id.in_(list(org_ids)),
                    Department.status == "active",
                )
            )
        ).all()
        return {(row[0], row[1]) for row in dept_rows}

    memberships = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    return {(m[0], m[1]) for m in memberships}


async def _resolve_upload_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    visibility: str | None,
    public_scope: str | None,
    org_id: str | None,
    dept_id: str | None,
    public_dept_ids: list[str] | None,
) -> tuple[KBVisibilityEnum, uuid.UUID, uuid.UUID | None, list[str] | None]:
    normalized_visibility = (visibility or "PRIVATE").strip().upper()
    if normalized_visibility not in {"PRIVATE", "PUBLIC", "DEPARTMENT", "ORGANIZATION"}:
        raise HTTPException(status_code=400, detail="Unsupported visibility")

    role = normalize_role(getattr(current_user, "role", "") or "")
    if normalized_visibility == "PRIVATE":
        org_memberships = (
            await session.exec(
                select(UserOrganizationMembership.org_id).where(
                    UserOrganizationMembership.user_id == current_user.id,
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
        ).all()
        allowed_orgs = {r if isinstance(r, uuid.UUID) else r[0] for r in org_memberships}
        if role in {"department_admin", "developer", "business_user"}:
            resolved_org_id, resolved_dept_id = await _resolve_default_scope(session, current_user)
            return KBVisibilityEnum.PRIVATE, resolved_org_id, resolved_dept_id, None
        if role == "super_admin":
            if not allowed_orgs:
                raise HTTPException(status_code=403, detail="No active organization scope found for user")
            return KBVisibilityEnum.PRIVATE, sorted(allowed_orgs, key=str)[0], None, None
        return KBVisibilityEnum.PRIVATE, None, None, None

    if normalized_visibility == "PUBLIC":
        if not public_scope:
            raise HTTPException(status_code=400, detail="public_scope is required for public visibility")
        normalized_visibility = "ORGANIZATION" if public_scope.strip().lower() == "organization" else "DEPARTMENT"

    if normalized_visibility == "DEPARTMENT":
        allowed = await _get_allowed_department_pairs_for_user(session, current_user)
        if role in {"super_admin", "root"}:
            if not org_id:
                raise HTTPException(status_code=400, detail="org_id is required for department visibility")
            parsed_org_id = uuid.UUID(org_id)
            if dept_id:
                parsed_dept_id = uuid.UUID(dept_id)
                if (parsed_org_id, parsed_dept_id) not in allowed:
                    raise HTTPException(status_code=403, detail="Selected department is outside your scope")
            requested_public_dept_ids = list(public_dept_ids or [])
            if not requested_public_dept_ids and dept_id:
                requested_public_dept_ids = [dept_id]
            if not requested_public_dept_ids:
                raise HTTPException(status_code=400, detail="Select at least one department")
            dept_uuid_list = [uuid.UUID(v) for v in requested_public_dept_ids]
            await _validate_departments_exist_for_org(session, parsed_org_id, dept_uuid_list)
            resolved_dept_id = uuid.UUID(requested_public_dept_ids[0]) if len(requested_public_dept_ids) == 1 else None
            return KBVisibilityEnum.DEPARTMENT, parsed_org_id, resolved_dept_id, requested_public_dept_ids
        if not allowed:
            raise HTTPException(status_code=403, detail="No active department scope found for user")
        default_org_id, default_dept_id = sorted(allowed, key=lambda x: (str(x[0]), str(x[1])))[0]
        return KBVisibilityEnum.DEPARTMENT, default_org_id, default_dept_id, [str(default_dept_id)]

    # ORGANIZATION
    org_memberships = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    allowed_orgs = {r if isinstance(r, uuid.UUID) else r[0] for r in org_memberships}
    if role == "root":
        if not org_id:
            raise HTTPException(status_code=400, detail="org_id is required for organization visibility")
        return KBVisibilityEnum.ORGANIZATION, uuid.UUID(org_id), None, None
    if not allowed_orgs:
        raise HTTPException(status_code=403, detail="No active organization scope found for user")
    parsed_org_id = uuid.UUID(org_id) if org_id else sorted(allowed_orgs, key=str)[0]
    if parsed_org_id not in allowed_orgs:
        raise HTTPException(status_code=403, detail="Selected organization is outside your scope")
    return KBVisibilityEnum.ORGANIZATION, parsed_org_id, None, None


async def _validate_departments_exist_for_org(
    session: DbSession,
    org_id: uuid.UUID,
    dept_ids: list[uuid.UUID],
) -> None:
    if not dept_ids:
        return
    rows = (
        await session.exec(
            select(Department.id).where(Department.org_id == org_id, Department.id.in_(dept_ids))
        )
    ).all()
    if len({str(r if isinstance(r, uuid.UUID) else r[0]) for r in rows}) != len({str(d) for d in dept_ids}):
        raise HTTPException(status_code=400, detail="One or more public_dept_ids are invalid for org_id")


def sanitize_knowledge_base_name(raw_name: str) -> str:
    clean_name = raw_name.strip()
    clean_name = clean_name.replace("\\", "_").replace("/", "_")
    clean_name = re.sub(r"[^A-Za-z0-9 _.-]", "_", clean_name)
    return re.sub(r"\s+", " ", clean_name).strip(" .")


def _safe_upload_error_detail(exc: Exception, fallback: str) -> str:
    raw_message = str(exc or "").strip()
    if not raw_message:
        return fallback
    if _SECRET_TOKEN_RE.search(raw_message):
        return fallback
    if len(raw_message) > 240:
        return fallback
    return raw_message


async def _can_access_existing_kb(session: DbSession, current_user: CurrentActiveUser, kb: KnowledgeBase) -> bool:
    role = normalize_role(getattr(current_user, "role", "") or "")
    if role == "root":
        return (
            kb.created_by == current_user.id
            and kb.org_id is None
            and kb.dept_id is None
        )

    if kb.created_by == current_user.id and kb.visibility == KBVisibilityEnum.PRIVATE:
        return True

    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    org_ids = {r if isinstance(r, uuid.UUID) else r[0] for r in org_rows}
    dept_pairs = await _get_allowed_department_pairs_for_user(session, current_user)
    dept_ids = {dept_id for _, dept_id in dept_pairs}

    if role == "super_admin" and kb.org_id and kb.org_id in org_ids:
        return True

    if kb.visibility == KBVisibilityEnum.PRIVATE:
        if role == "department_admin":
            kb_dept_ids = {str(v) for v in (kb.public_dept_ids or [])}
            if kb.dept_id:
                kb_dept_ids.add(str(kb.dept_id))
            return bool(kb_dept_ids.intersection({str(d) for d in dept_ids}))
        return False
    if kb.visibility == KBVisibilityEnum.DEPARTMENT:
        kb_dept_ids = {str(v) for v in (kb.public_dept_ids or [])}
        if kb.dept_id:
            kb_dept_ids.add(str(kb.dept_id))
        return bool(kb_dept_ids.intersection({str(d) for d in dept_ids}))
    if kb.visibility == KBVisibilityEnum.ORGANIZATION:
        return bool(kb.org_id and kb.org_id in org_ids)
    return False


async def _get_or_create_knowledge_base(
    session: DbSession,
    current_user: CurrentActiveUser,
    knowledge_base_name: str,
    visibility: KBVisibilityEnum,
    org_id: uuid.UUID,
    dept_id: uuid.UUID | None,
    public_dept_ids: list[str] | None,
) -> KnowledgeBase:
    existing = (
        await session.exec(
            select(KnowledgeBase).where(
                KnowledgeBase.name == knowledge_base_name,
                KnowledgeBase.org_id == org_id,
                KnowledgeBase.dept_id == dept_id,
            )
        )
    ).first()
    if existing:
        if not await _can_access_existing_kb(session, current_user, existing):
            raise HTTPException(status_code=403, detail="Not authorized to use this knowledge base")
        # Adding files into an existing KB counts as a modification —
        # surface "modified by" in the management UI.
        existing.updated_by = current_user.id
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        return existing

    kb = KnowledgeBase(
        name=knowledge_base_name,
        visibility=visibility,
        org_id=org_id,
        dept_id=dept_id,
        public_dept_ids=public_dept_ids,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(kb)
    await session.flush()
    return kb


async def _require_knowledge_base_upload_permission(current_user: CurrentActiveUser) -> None:
    role = normalize_role(getattr(current_user, "role", None))
    if role == "root":
        return

    allowed_actions = await get_permissions_for_role(current_user.role)
    if "add_new_knowledge" not in allowed_actions:
        raise HTTPException(
            status_code=403,
            detail=f"User {current_user.username} lacks permission: add_new_knowledge",
        )


async def byte_stream_generator(file_input, chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:
    """Convert bytes object or stream into an async generator that yields chunks."""
    if isinstance(file_input, bytes):
        # Handle bytes object
        for i in range(0, len(file_input), chunk_size):
            yield file_input[i : i + chunk_size]
    # Handle stream object
    elif hasattr(file_input, "read"):
        while True:
            chunk = await file_input.read(chunk_size) if callable(file_input.read) else file_input.read(chunk_size)
            if not chunk:
                break
            yield chunk
    else:
        # Handle async iterator
        async for chunk in file_input:
            yield chunk


async def fetch_file_object(file_id: uuid.UUID, current_user: CurrentActiveUser, session: DbSession):
    # Fetch the file from the DB
    visibility_filters = await _build_file_visibility_filters(session, current_user)
    stmt = select(UserFile).where(UserFile.id == file_id).where(or_(*visibility_filters))
    results = await session.exec(stmt)
    file = results.first()

    # Check if the file exists
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    return file


async def save_file_routine(file, storage_service, current_user: CurrentActiveUser, file_content=None, file_name=None):
    """Routine to save the file content to the storage service."""
    file_id = uuid.uuid4()

    if not file_content:
        file_content = await file.read()
    if not file_name:
        file_name = file.filename

    # Save the file using the storage service.
    await storage_service.save_file(agent_id=str(current_user.id), file_name=file_name, data=file_content)

    return file_id, file_name


def get_storage_relative_path(file_path: str, user_id: uuid.UUID) -> str:
    """Convert stored DB path into storage-relative path under user root."""
    user_prefix = f"{user_id}/"
    if file_path.startswith(user_prefix):
        return file_path[len(user_prefix) :]
    return file_path


@router.post("", status_code=HTTPStatus.CREATED)
@router.post("/", status_code=HTTPStatus.CREATED)
async def upload_user_file(
    file: Annotated[UploadFile, File(...)],
    session: DbSession,
    current_user: CurrentActiveUser,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
    knowledge_base_name: Annotated[str | None, Form()] = None,
    visibility: Annotated[str | None, Form()] = None,
    public_scope: Annotated[str | None, Form()] = None,
    org_id: Annotated[str | None, Form()] = None,
    dept_id: Annotated[str | None, Form()] = None,
    public_dept_ids: Annotated[list[str] | None, Form()] = None,
) -> UserUploadFileResponse:

    """Upload a file for the current user and track it in the database."""
    # Get the max allowed file size from settings (in MB)
    try:
        max_file_size_upload = settings_service.settings.max_file_size_upload
    except Exception as e:
        logger.exception("Knowledge hub upload failed while reading settings")
        raise HTTPException(
            status_code=500,
            detail=_safe_upload_error_detail(e, "Upload settings are unavailable right now."),
        ) from e

    # Validate that a file is actually provided
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate file size (convert MB to bytes)
    if file.size > max_file_size_upload * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File size is larger than the maximum file size {max_file_size_upload}MB.",
        )

    # Create a new database record for the uploaded file.
    try:
        new_filename = file.filename
        try:
            root_filename, file_extension = new_filename.rsplit(".", 1)
        except ValueError:
            root_filename, file_extension = new_filename, ""

        # Resolve the target knowledge base FIRST so the dedup query below can
        # be scoped to (user_id, knowledge_base_id). Otherwise a fresh KB would
        # still bump its counter past filenames living in unrelated KBs on the
        # same deployment.
        safe_knowledge_base_name = ""
        knowledge_base: KnowledgeBase | None = None
        if knowledge_base_name:
            await _require_knowledge_base_upload_permission(current_user)
            safe_knowledge_base_name = sanitize_knowledge_base_name(knowledge_base_name)
            if not safe_knowledge_base_name:
                raise HTTPException(status_code=400, detail="Invalid knowledge base name")
            kb_visibility, kb_org_id, kb_dept_id, kb_public_dept_ids = await _resolve_upload_scope(
                session=session,
                current_user=current_user,
                visibility=visibility,
                public_scope=public_scope,
                org_id=org_id,
                dept_id=dept_id,
                public_dept_ids=public_dept_ids,
            )
            knowledge_base = await _get_or_create_knowledge_base(
                session=session,
                current_user=current_user,
                knowledge_base_name=safe_knowledge_base_name,
                visibility=kb_visibility,
                org_id=kb_org_id,
                dept_id=kb_dept_id,
                public_dept_ids=kb_public_dept_ids,
            )

        # Special handling for the MCP servers config file: always keep the
        # same root filename and replace any prior record.
        if root_filename == MCP_SERVERS_FILE:
            existing_mcp_file = await get_file_by_name(root_filename, current_user, session)
            if existing_mcp_file:
                await delete_file(existing_mcp_file.id, current_user, session, storage_service)
            unique_filename = new_filename
            # MCP records continue to be keyed by the bare root filename so
            # get_file_by_name(MCP_SERVERS_FILE, ...) in mcp_config.py keeps working.
            name_to_store = root_filename
        else:
            # Dedup is scoped to (user_id, knowledge_base_id, root, extension).
            # A file is treated as a duplicate ONLY when ALL of these match: the
            # same user, the same KB, the same root name, AND the same extension.
            # Different extension → not a duplicate. Different KB → not a
            # duplicate. The DB stores `name` *with* the extension so the
            # composite UNIQUE(user_id, knowledge_base_id, name) constraint
            # admits same-name files across different extensions or KBs.
            target_ext = file_extension.lower() if file_extension else ""
            kb_id = knowledge_base.id if knowledge_base else None

            stmt = (
                select(UserFile)
                .where(UserFile.user_id == current_user.id)
                .where(UserFile.knowledge_base_id == kb_id)
                .where(col(UserFile.name).like(f"{root_filename}%"))
            )
            existing_files = await session.exec(stmt)
            files = existing_files.all()

            counts: list[int] = []
            same_name_exists = False

            for my_file in files:
                # Resolve the stored file's extension from its path — `name` may
                # or may not include the extension depending on when the row was
                # written, but `path` always carries the real extension.
                my_file_path = getattr(my_file, "path", "") or ""
                my_file_basename = my_file_path.rsplit("/", 1)[-1]
                my_file_ext = (
                    my_file_basename.rsplit(".", 1)[1].lower()
                    if "." in my_file_basename
                    else ""
                )
                if my_file_ext != target_ext:
                    continue

                # Strip a trailing ".ext" from `name` if present so the root
                # comparison is uniform across legacy (no-ext) and new
                # (with-ext) rows.
                stored_root = my_file.name
                if target_ext and stored_root.lower().endswith(f".{target_ext}"):
                    stored_root = stored_root[: -(len(target_ext) + 1)]

                if stored_root == root_filename:
                    same_name_exists = True
                    continue

                match = re.fullmatch(
                    rf"{re.escape(root_filename)} \((\d+)\)", stored_root
                )
                if match:
                    counts.append(int(match.group(1)))

            if same_name_exists or counts:
                next_count = (max(counts) if counts else 0) + 1
                root_filename = f"{root_filename} ({next_count})"

            # Final filename with extension for both storage and the `name` column.
            unique_filename = f"{root_filename}.{file_extension}" if file_extension else root_filename
            name_to_store = unique_filename

        # For KB uploads, include KB id in storage path for stable unique mapping.
        # Final physical path stays rooted by user id in storage service:
        # <storage>/<user_id>/<kb_id>/<kb_name>/<file_name>
        if knowledge_base and safe_knowledge_base_name:
            storage_file_name = f"{knowledge_base.id}/{safe_knowledge_base_name}/{unique_filename}"
        else:
            storage_file_name = unique_filename

        # Read file content and save with unique filename
        try:
            file_id, stored_file_name = await save_file_routine(
                file, storage_service, current_user, file_name=storage_file_name
            )
        except Exception as e:
            logger.exception("Knowledge hub upload failed while saving file")
            await session.rollback()
            raise HTTPException(
                status_code=500,
                detail=_safe_upload_error_detail(e, "Unable to save the uploaded file."),
            ) from e

        # Compute the file size based on the path
        file_size = await storage_service.get_file_size(
            agent_id=str(current_user.id),
            file_name=stored_file_name,
        )

        # Create a new file record
        new_file = UserFile(
            id=file_id,
            user_id=current_user.id,
            org_id=knowledge_base.org_id if knowledge_base else None,
            dept_id=knowledge_base.dept_id if knowledge_base else None,
            knowledge_base_id=knowledge_base.id if knowledge_base else None,
            name=name_to_store,
            path=f"{current_user.id}/{storage_file_name}",
            size=file_size,
        )
        session.add(new_file)

        await session.commit()
        await session.refresh(new_file)
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        # Optionally, you could also delete the file from disk if the DB insert fails.
        logger.exception("Knowledge hub upload failed while writing database records")
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=_safe_upload_error_detail(e, "Unable to complete the upload."),
        ) from e

    # Force forward-slash separators — on Windows, Path() stringifies with
    # backslashes, which breaks frontend filename extraction (split("/")).
    return UserUploadFileResponse(user_id=str(current_user.id), file_path=Path(str(new_file.path).replace("\\", "/")))


async def get_file_by_name(
    file_name: str,  # The name of the file to search for
    current_user: CurrentActiveUser,
    session: DbSession,
) -> UserFile | None:
    """Get the file associated with a given file name for the current user."""
    try:
        # Fetch from the UserFile table
        stmt = select(UserFile).where(UserFile.user_id == current_user.id).where(UserFile.name == file_name)
        result = await session.exec(stmt)

        return result.first() or None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching file: {e}") from e


async def load_sample_files(current_user: CurrentActiveUser, session: DbSession, storage_service: StorageService):
    # Check if the sample files in the SAMPLE_DATA_DIR exist
    for sample_file_path in Path(SAMPLE_DATA_DIR).iterdir():
        sample_file_name = sample_file_path.name
        root_filename, _ = sample_file_name.rsplit(".", 1)

        # Check if the sample file exists in the storage service
        existing_sample_file = await get_file_by_name(
            file_name=root_filename, current_user=current_user, session=session
        )
        if existing_sample_file:
            continue

        # Read the binary data of the sample file
        binary_data = sample_file_path.read_bytes()

        # Write the sample file content to the storage service
        file_id, _ = await save_file_routine(
            sample_file_path,
            storage_service,
            current_user,
            file_content=binary_data,
            file_name=sample_file_name,
        )
        file_size = await storage_service.get_file_size(
            agent_id=str(current_user.id),
            file_name=sample_file_name,
        )
        # Create a UserFile object for the sample file
        sample_file = UserFile(
            id=file_id,
            user_id=current_user.id,
            name=root_filename,
            path=sample_file_name,
            size=file_size,
        )

        session.add(sample_file)

        await session.commit()
        await session.refresh(sample_file)


@router.get("")
@router.get("/", status_code=HTTPStatus.OK)
async def list_files(
    current_user: CurrentActiveUser,
    session: DbSession,
    # storage_service: Annotated[StorageService, Depends(get_storage_service)],
) -> list[UserFile]:
    """List the files available to the current user."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        stmt = select(UserFile).where(or_(*visibility_filters))
        results = await session.exec(stmt)

        full_list = list(results)

        # Filter out the _mcp_servers file
        return [file for file in full_list if file.name != MCP_SERVERS_FILE]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {e}") from e


@router.delete("/batch/", status_code=HTTPStatus.OK)
async def delete_files_batch(
    file_ids: list[uuid.UUID],
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete multiple files by their IDs."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(col(UserFile.id).in_(file_ids), or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        if not files:
            raise HTTPException(status_code=404, detail="No files found")

        # Delete all files from the storage service
        for file in files:
            storage_path = get_storage_relative_path(file.path, file.user_id)
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
            await session.delete(file)

        # Delete all files from the database
        await session.commit()  # Commit deletion

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()  # Rollback on failure
        raise HTTPException(status_code=500, detail=f"Error deleting files: {e}") from e

    return {"message": f"{len(files)} files deleted successfully"}


@router.post("/batch/", status_code=HTTPStatus.OK)
async def download_files_batch(
    file_ids: list[uuid.UUID],
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Download multiple files as a zip file by their IDs."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(col(UserFile.id).in_(file_ids), or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        if not files:
            raise HTTPException(status_code=404, detail="No files found")

        # Create a byte stream to hold the ZIP file
        zip_stream = io.BytesIO()

        # Create a ZIP file
        with zipfile.ZipFile(zip_stream, "w") as zip_file:
            for file in files:
                # Get the file content from storage
                storage_path = get_storage_relative_path(file.path, file.user_id)
                file_content = await storage_service.get_file(
                    agent_id=str(file.user_id), file_name=storage_path
                )

                # Get the file extension from the original filename. Legacy
                # rows store `name` without extension; new rows store it with —
                # only append when it isn't already there.
                file_extension = Path(file.path).suffix
                filename_with_extension = (
                    file.name
                    if file_extension and file.name.lower().endswith(file_extension.lower())
                    else f"{file.name}{file_extension}"
                )

                # Write the file to the ZIP with the proper extension
                zip_file.writestr(filename_with_extension, file_content)

        # Seek to the beginning of the byte stream
        zip_stream.seek(0)

        # Generate the filename with the current datetime
        current_time = datetime.now(tz=ZoneInfo("UTC")).astimezone().strftime("%Y%m%d_%H%M%S")
        filename = f"{current_time}_agentcore_files.zip"

        return StreamingResponse(
            zip_stream,
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading files: {e}") from e


async def read_file_content(file_stream: AsyncIterable[bytes] | bytes, *, decode: bool = True) -> str | bytes:
    """Read file content from a stream or bytes into a string or bytes.

    Args:
        file_stream: An async iterable yielding bytes or a bytes object.
        decode: If True, decode the content to UTF-8; otherwise, return bytes.

    Returns:
        The file content as a string (if decode=True) or bytes.

    Raises:
        ValueError: If the stream yields non-bytes chunks.
        HTTPException: If decoding fails or an error occurs while reading.
    """
    content = b""
    try:
        if isinstance(file_stream, bytes):
            content = file_stream
        else:
            async for chunk in file_stream:
                if not isinstance(chunk, bytes):
                    msg = "File stream must yield bytes"
                    raise TypeError(msg)
                content += chunk
        if not decode:
            return content
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=500, detail="Invalid file encoding") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Error reading file: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading file: {exc}") from exc


@router.get("/{file_id}")
async def download_file(
    file_id: uuid.UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    *,
    return_content: bool = False,
):
    """Download a file by its ID or return its content as a string/bytes.

    Args:
        file_id: UUID of the file.
        current_user: Authenticated user.
        session: Database session.
        storage_service: File storage service.
        return_content: If True, return raw content (str) instead of StreamingResponse.

    Returns:
        StreamingResponse for client downloads or str for internal use.
    """
    try:
        # Fetch the file from the DB
        file = await fetch_file_object(file_id, current_user, session)
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        storage_path = get_storage_relative_path(file.path, file.user_id)

        # Get file stream
        file_stream = await storage_service.get_file(agent_id=str(file.user_id), file_name=storage_path)

        if file_stream is None:
            raise HTTPException(status_code=404, detail="File stream not available")

        # If return_content is True, read the file content and return it
        if return_content:
            return await read_file_content(file_stream, decode=True)

        # For streaming, ensure file_stream is an async iterator returning bytes
        byte_stream = byte_stream_generator(file_stream)

        # Create the filename with extension. Legacy rows store `name` without
        # extension; new rows store it with — only append when it isn't already
        # there.
        file_extension = Path(file.path).suffix
        filename_with_extension = (
            file.name
            if file_extension and file.name.lower().endswith(file_extension.lower())
            else f"{file.name}{file_extension}"
        )

        # Return the file as a streaming response
        return StreamingResponse(
            byte_stream,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename_with_extension}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {e}") from e


@router.put("/{file_id}")
async def edit_file_name(
    file_id: uuid.UUID,
    name: str,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> UserUploadFileResponse:
    """Edit the name of a file by its ID."""
    try:
        # Fetch the file from the DB
        file = await fetch_file_object(file_id, current_user, session)

        # Update the file name
        file.name = name
        await session.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error editing file: {e}") from e

    return UserUploadFileResponse(user_id=str(current_user.id), file_path=Path(str(file.path).replace("\\", "/")))


@router.delete("/{file_id}")
async def delete_file(
    file_id: uuid.UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete a file by its ID."""
    try:
        # Fetch the file object
        file_to_delete = await fetch_file_object(file_id, current_user, session)
        if not file_to_delete:
            raise HTTPException(status_code=404, detail="File not found")

        # Delete the file from the storage service
        storage_path = get_storage_relative_path(file_to_delete.path, file_to_delete.user_id)
        await storage_service.delete_file(agent_id=str(file_to_delete.user_id), file_name=storage_path)

        # Delete from the database
        await session.delete(file_to_delete)
        await session.commit()

    except HTTPException:
        # Re-raise HTTPException to avoid being caught by the generic exception handler
        raise
    except Exception as e:
        # Log and return a generic server error
        logger.error("Error deleting file %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Error deleting file: {e}") from e
    return {"detail": f"File {file_to_delete.name} deleted successfully"}


@router.delete("")
@router.delete("/", status_code=HTTPStatus.OK)
async def delete_all_files(
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete all files for the current user."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        # Delete all files from the storage service
        for file in files:
            storage_path = get_storage_relative_path(file.path, file.user_id)
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
            await session.delete(file)

        # Delete all files from the database
        await session.commit()  # Commit deletion

    except Exception as e:
        await session.rollback()  # Rollback on failure
        raise HTTPException(status_code=500, detail=f"Error deleting files: {e}") from e

    return {"message": "All files deleted successfully"}
