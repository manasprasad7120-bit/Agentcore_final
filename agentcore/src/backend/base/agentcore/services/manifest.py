"""Manifest YAML helpers -- add / remove agent entries directly in Git repo."""

from __future__ import annotations

from loguru import logger


_ENV_TO_NUMERIC = {"dev": 0, "uat": 1, "prod": 2}


def _normalize_env(environment: str) -> int:
    """Convert env name to numeric code (dev→0, uat→1, prod→2). Pass-through if already numeric."""
    val = environment.lower()
    if val in _ENV_TO_NUMERIC:
        return _ENV_TO_NUMERIC[val]
    return int(val)


def _norm_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _norm_version(value: object | None) -> str:
    raw = _norm_str(value)
    if raw.startswith("v"):
        raw = raw[1:]
    return raw


def add_manifest_entry(
    *,
    agent_id: str,
    agent_name: str,
    version_number: str,
    environment: str,
    deployment_id: str,
) -> None:
    """Add an agent entry directly in the Git repo. Idempotent -- skips if deployment_id already present."""
    try:
        from agentcore.services.git_manifest import read_manifest_from_git, push_manifest_to_git

        data = read_manifest_from_git()
        agents: list = data.get("agents", [])

        if any(d.get("deployment_id") == deployment_id for d in agents):
            logger.debug(f"[MANIFEST] Entry for {deployment_id} already exists, skipping add.")
            return

        env_code = _normalize_env(environment)
        agents.append({
            "agent_id": agent_id,
            "agent_name": agent_name,
            "version_number": version_number,
            "environment": env_code,
            "deployment_id": deployment_id,
        })
        updated = {"agents": agents}
        push_manifest_to_git(updated, f"manifest: add agent {agent_name} ({deployment_id})")
        logger.info(f"[MANIFEST] Added entry for deployment_id={deployment_id} (total: {len(agents)})")
    except Exception as err:
        logger.warning(f"[MANIFEST] Failed to add entry: {err}")


def remove_manifest_entry(
    *,
    deployment_id: str,
) -> None:
    """Remove the entry matching deployment_id directly from the Git repo. No-op if not found."""
    try:
        from agentcore.services.git_manifest import read_manifest_from_git, push_manifest_to_git

        data = read_manifest_from_git()
        agents: list = data.get("agents", [])

        original_len = len(agents)
        agents = [d for d in agents if d.get("deployment_id") != deployment_id]

        if len(agents) == original_len:
            logger.debug(f"[MANIFEST] No entry found for {deployment_id}, nothing to remove.")
            return

        updated = {"agents": agents}
        push_manifest_to_git(updated, f"manifest: remove deployment {deployment_id}")
        logger.info(f"[MANIFEST] Removed entry for deployment_id={deployment_id} (remaining: {len(agents)})")
    except Exception as err:
        logger.warning(f"[MANIFEST] Failed to remove entry: {err}")


def remove_manifest_entry_for_uat_to_prod(
    *,
    deployment_id: str,
    agent_id: str,
    version_number: str,
    environment: str | int = "uat",
) -> None:
    """Remove manifest row during UAT->PROD move without changing existing remove behavior.

    Uses agent-first matching (agent_id anchor) and narrows with env + (version or deployment_id).
    """
    try:
        from agentcore.services.git_manifest import read_manifest_from_git, push_manifest_to_git

        data = read_manifest_from_git()
        agents: list = data.get("agents", [])

        target_agent = _norm_str(agent_id)
        target_version = _norm_version(version_number)
        target_deploy = _norm_str(deployment_id)
        try:
            target_env = _normalize_env(str(environment))
        except Exception:
            target_env = None

        filtered_agents: list = []
        removed_count = 0

        for row in agents:
            row_agent = _norm_str(row.get("agent_id"))
            row_version = _norm_version(row.get("version_number"))
            row_deploy = _norm_str(row.get("deployment_id") or row.get("deploy_id"))
            try:
                row_env = _normalize_env(str(row.get("environment")))
            except Exception:
                row_env = None

            same_agent = row_agent == target_agent
            same_env = (target_env is None) or (row_env == target_env)
            same_version = bool(target_version) and row_version == target_version
            same_deploy = bool(target_deploy) and row_deploy == target_deploy

            if same_agent and same_env and (same_version or same_deploy):
                removed_count += 1
                continue

            filtered_agents.append(row)

        if removed_count == 0:
            logger.debug(
                "[MANIFEST] No UAT->PROD row found to remove: "
                f"agent_id={agent_id}, version={version_number}, env={environment}, "
                f"deployment_id={deployment_id}",
            )
            return

        updated = {"agents": filtered_agents}
        push_manifest_to_git(updated, f"manifest: remove deployment {deployment_id}")
        logger.info(
            "[MANIFEST] Removed UAT->PROD entry/entries: "
            f"agent_id={agent_id}, version={version_number}, env={environment}, "
            f"deployment_id={deployment_id}, removed={removed_count}, remaining={len(filtered_agents)}",
        )
    except Exception as err:
        logger.warning(f"[MANIFEST] Failed UAT->PROD specific remove: {err}")
