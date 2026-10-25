from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlalchemy import desc
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.api.v1_schemas import AgentApiKeyCreatedResponse, AgentApiKeyResponse
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_api_key.model import AgentApiKey
from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT, DeploymentUATStatusEnum
from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd, DeploymentPRODStatusEnum
from agentcore.services.auth.utils import generate_agent_api_key


router = APIRouter(tags=["APIKey"], prefix="/api_key")


@router.get("/agent/{agent_id}", response_model=list[AgentApiKeyResponse])
async def list_agent_api_keys(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
):
    """List all API keys for an agent (never returns full key, only prefix)."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    records = (
        await session.exec(
            select(AgentApiKey)
            .where(AgentApiKey.agent_id == agent_id)
            .order_by(AgentApiKey.created_at.desc())
        )
    ).all()

    return [
        AgentApiKeyResponse(
            id=r.id,
            agent_id=r.agent_id,
            deployment_id=r.deployment_id,
            version=r.version,
            environment=r.environment,
            key_prefix=r.key_prefix,
            is_active=r.is_active,
            created_at=r.created_at.isoformat(),
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
        )
        for r in records
    ]


@router.post("/agent/{agent_id}/rotate", response_model=AgentApiKeyCreatedResponse)
async def rotate_agent_api_key(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    environment: str = "uat",
    version: str | None = None,
):
    """Revoke all active keys for an agent+environment+version and generate a new one.

    If version is provided (e.g. "v2"), generates a key for that specific deployment version.
    If version is omitted, generates a key for the latest published deployment.

    Returns the new plaintext key (one-time only).
    """
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # Look up the deployment for the requested version (or latest)
    deployment_id = None
    version_number = int(version.lstrip("v")) if version else None

    if environment == "uat":
        stmt = (
            select(AgentDeploymentUAT)
            .where(AgentDeploymentUAT.agent_id == agent_id)
            .where(AgentDeploymentUAT.status == DeploymentUATStatusEnum.PUBLISHED)
        )
        if version_number is not None:
            stmt = stmt.where(AgentDeploymentUAT.version_number == version_number)
        else:
            stmt = stmt.where(AgentDeploymentUAT.is_active == True).order_by(  # noqa: E712
                desc(AgentDeploymentUAT.version_number)
            )
        dep = (await session.exec(stmt)).first()
        if dep:
            deployment_id = dep.id
            version = f"v{dep.version_number}"
    elif environment == "prod":
        stmt = (
            select(AgentDeploymentProd)
            .where(AgentDeploymentProd.agent_id == agent_id)
            .where(AgentDeploymentProd.status == DeploymentPRODStatusEnum.PUBLISHED)
        )
        if version_number is not None:
            stmt = stmt.where(AgentDeploymentProd.version_number == version_number)
        else:
            stmt = stmt.where(AgentDeploymentProd.is_active == True).order_by(  # noqa: E712
                desc(AgentDeploymentProd.version_number)
            )
        dep = (await session.exec(stmt)).first()
        if dep:
            deployment_id = dep.id
            version = f"v{dep.version_number}"

    if not deployment_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No published {environment.upper()} deployment "
                   f"{'version ' + version if version else ''} found for this agent",
        )

    # Revoke all existing active keys for this agent+environment+deployment
    existing = (
        await session.exec(
            select(AgentApiKey)
            .where(AgentApiKey.agent_id == agent_id)
            .where(AgentApiKey.environment == environment)
            .where(AgentApiKey.deployment_id == deployment_id)
            .where(AgentApiKey.is_active == True)  # noqa: E712
        )
    ).all()

    for key_record in existing:
        key_record.is_active = False
        session.add(key_record)

    # Generate new key
    plaintext_key, key_hash, key_prefix = generate_agent_api_key()
    new_record = AgentApiKey(
        agent_id=agent_id,
        deployment_id=deployment_id,
        version=version,
        environment=environment,
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_active=True,
        created_by=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(new_record)
    await session.commit()
    await session.refresh(new_record)

    logger.info(
        f"Rotated API key for agent={agent_id} env={environment} "
        f"(revoked {len(existing)} old key(s), new prefix={key_prefix})"
    )

    return AgentApiKeyCreatedResponse(
        id=new_record.id,
        agent_id=new_record.agent_id,
        deployment_id=new_record.deployment_id,
        version=new_record.version,
        environment=new_record.environment,
        key_prefix=new_record.key_prefix,
        is_active=True,
        created_at=new_record.created_at.isoformat(),
        api_key=plaintext_key,
    )


@router.delete("/{api_key_id}")
async def revoke_api_key(
    api_key_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
):
    """Revoke (soft-delete) an API key by setting is_active=False."""
    record = await session.get(AgentApiKey, api_key_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    if not record.is_active:
        return {"detail": "API key is already revoked", "id": str(api_key_id)}

    record.is_active = False
    session.add(record)
    await session.commit()

    logger.info(f"Revoked API key {api_key_id} (prefix={record.key_prefix})")
    return {"detail": "API key revoked successfully", "id": str(api_key_id)}
