from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlmodel import select

from agentcore.services.database.models.approval_notification.model import ApprovalNotification
from agentcore.services.database.models.user.model import User


async def upsert_approval_notification(
    session,
    *,
    recipient_user_id: UUID,
    entity_type: str,
    entity_id: str,
    title: str,
    link: str = "/approval",
) -> ApprovalNotification:
    stmt = select(ApprovalNotification).where(
        ApprovalNotification.recipient_user_id == recipient_user_id,
        ApprovalNotification.entity_type == entity_type,
        ApprovalNotification.entity_id == entity_id,
    )
    existing = (await session.exec(stmt)).first()
    now = datetime.now(timezone.utc)

    if existing:
        existing.title = title
        existing.link = link
        existing.is_read = False
        existing.read_at = None
        existing.created_at = now
        session.add(existing)
        await session.flush()
        return existing

    row = ApprovalNotification(
        recipient_user_id=recipient_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        link=link,
        is_read=False,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def notify_root_approvers(
    session,
    *,
    entity_type: str,
    entity_id: str,
    title: str,
    link: str = "/approval",
) -> list[ApprovalNotification]:
    roots = (
        await session.exec(
            select(User).where(
                func.lower(User.role) == "root",
                User.deleted_at.is_(None),
                User.is_active == True,  # noqa: E712
            )
        )
    ).all()

    notifications: list[ApprovalNotification] = []
    for user in roots:
        notifications.append(
            await upsert_approval_notification(
                session,
                recipient_user_id=user.id,
                entity_type=entity_type,
                entity_id=entity_id,
                title=title,
                link=link,
            )
        )
    return notifications
