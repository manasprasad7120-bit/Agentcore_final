from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import toml
from sqlalchemy import text
from sqlmodel import select

from app.database import session_scope
from app.models.package_inventory import Package, ProductRelease

logger = logging.getLogger(__name__)
ACTIVE_END_DATE = date(9999, 12, 31)
SERVICE_NAME = "guardrails-service"


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _resolve_project_file(filename: str, env_var: str) -> Path:
    configured_path = os.getenv(env_var)
    if configured_path:
        return Path(configured_path).expanduser()

    module_dir = Path(__file__).resolve().parent
    search_roots = [Path.cwd(), module_dir, *module_dir.parents]
    seen_roots: set[Path] = set()
    for root in search_roots:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        candidate = root / filename
        if candidate.exists():
            return candidate

    fallback = Path.cwd() / filename
    logger.warning(
        "%s not configured via %s and not found by upward search; defaulting to %s",
        filename,
        env_var,
        fallback,
    )
    return fallback


def _parse_pyproject(pyproject_path: Path) -> list[dict[str, str]]:
    if not pyproject_path.exists():
        logger.warning("pyproject.toml not found at %s", pyproject_path)
        return []

    data = toml.loads(pyproject_path.read_text(encoding="utf-8"))
    raw_deps: list[str] = data.get("project", {}).get("dependencies", [])

    results: list[dict[str, str]] = []
    for dep in raw_deps:
        dep_clean = dep.split(";")[0].strip()
        match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9._-]*)(.*)", dep_clean)
        if match:
            results.append(
                {
                    "name": match.group(1).strip().lower(),
                    "version_spec": match.group(2).strip() or None,
                }
            )
    return results


def _parse_uv_lock(uv_lock_path: Path) -> list[dict[str, Any]]:
    if not uv_lock_path.exists():
        logger.warning("uv.lock not found at %s", uv_lock_path)
        return []

    data = toml.loads(uv_lock_path.read_text(encoding="utf-8"))
    packages = data.get("package", [])
    return packages if isinstance(packages, list) else []


async def _resolve_active_release_id():
    try:
        async with session_scope() as session:
            release_check = (
                await session.execute(text("SELECT to_regclass('public.product_release') IS NOT NULL"))
            ).first()
            release_table_exists = bool(release_check[0]) if release_check else False
            if not release_table_exists:
                return None

            active_release = (
                await session.execute(
                    select(ProductRelease).where(ProductRelease.end_date == ACTIVE_END_DATE)
                )
            ).scalars().first()
            return active_release.id if active_release else None
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not resolve active release for package sync: %s", exc)
        return None


def build_runtime_metadata() -> dict[str, str | None]:
    return {
        "snapshot_id": os.getenv("PACKAGE_SNAPSHOT_ID") or None,
        "build_id": os.getenv("BUILD_BUILDID") or os.getenv("PACKAGE_BUILD_ID") or None,
        "commit_sha": os.getenv("BUILD_SOURCEVERSION") or os.getenv("PACKAGE_COMMIT_SHA") or None,
    }


async def sync_packages_to_db() -> None:
    async with session_scope() as session:
        package_check = (await session.execute(text("SELECT to_regclass('public.package') IS NOT NULL"))).first()
        package_table_exists = bool(package_check[0]) if package_check else False
        if not package_table_exists:
            logger.warning("Package table missing; skipping guardrails-service package sync")
            return

    pyproject_path = _resolve_project_file("pyproject.toml", "PYPROJECT_PATH")
    uv_lock_path = _resolve_project_file("uv.lock", "UV_LOCK_PATH")
    declared = _parse_pyproject(pyproject_path)
    lock_pkgs = _parse_uv_lock(uv_lock_path)

    if not lock_pkgs:
        logger.warning("No packages found in %s; skipping guardrails-service package sync", uv_lock_path)
        return

    metadata = build_runtime_metadata()
    release_id = await _resolve_active_release_id()
    declared_names = {_normalize(d["name"]) for d in declared}
    lock_map: dict[str, dict[str, Any]] = {}
    for pkg in lock_pkgs:
        pkg_name = pkg.get("name")
        if pkg_name:
            lock_map[_normalize(pkg_name)] = pkg

    required_by_map: dict[str, list[str]] = {}
    required_by_details_map: dict[str, list[dict[str, str]]] = {}
    for pkg in lock_pkgs:
        requester_name = str(pkg.get("name") or "").strip()
        requester_version = str(pkg.get("version") or "unknown").strip()
        if not requester_name:
            continue
        for dep in pkg.get("dependencies", []):
            dep_name = dep.get("name")
            if not dep_name:
                continue
            dep_norm = _normalize(dep_name)
            required_by_map.setdefault(dep_norm, []).append(requester_name)
            required_by_details_map.setdefault(dep_norm, []).append(
                {"name": requester_name, "version": requester_version}
            )

    rows: list[dict[str, Any]] = []
    for dep in declared:
        lock_entry = lock_map.get(_normalize(dep["name"]), {})
        rows.append(
            {
                "name": dep["name"],
                "service_name": SERVICE_NAME,
                "version": str(lock_entry.get("version", "unknown")),
                "version_spec": dep["version_spec"],
                "package_type": "managed",
                "snapshot_id": metadata["snapshot_id"],
                "build_id": metadata["build_id"],
                "commit_sha": metadata["commit_sha"],
                "release_id": release_id,
                "required_by": None,
                "required_by_details": None,
                "source": lock_entry.get("source"),
            }
        )

    seen_transitive: set[str] = set()
    for pkg in lock_pkgs:
        pkg_name = str(pkg.get("name") or "").strip()
        if not pkg_name:
            continue
        pkg_norm = _normalize(pkg_name)
        if pkg_norm in declared_names or pkg_norm in seen_transitive:
            continue
        source = pkg.get("source", {})
        if isinstance(source, dict) and "editable" in source:
            continue
        seen_transitive.add(pkg_norm)
        rows.append(
            {
                "name": pkg_name,
                "service_name": SERVICE_NAME,
                "version": str(pkg.get("version", "unknown")),
                "version_spec": None,
                "package_type": "transitive",
                "snapshot_id": metadata["snapshot_id"],
                "build_id": metadata["build_id"],
                "commit_sha": metadata["commit_sha"],
                "release_id": release_id,
                "required_by": required_by_map.get(pkg_norm, []) or None,
                "required_by_details": required_by_details_map.get(pkg_norm, []) or None,
                "source": source if source else None,
            }
        )

    now = datetime.now(timezone.utc)
    today = now.date()

    async with session_scope() as session:
        current_rows = (
            await session.execute(
                select(Package).where(
                    Package.service_name == SERVICE_NAME,
                    Package.end_date == ACTIVE_END_DATE,
                )
            )
        ).scalars().all()
        current_map = {
            (_normalize(row.name), row.package_type): row
            for row in current_rows
        }

        incoming_keys: set[tuple[str, str]] = set()
        for row in rows:
            key = (_normalize(row["name"]), row["package_type"])
            incoming_keys.add(key)
            existing = current_map.get(key)

            if existing is None:
                session.add(
                    Package(
                        name=row["name"],
                        service_name=row["service_name"],
                        version=row["version"],
                        version_spec=row["version_spec"],
                        package_type=row["package_type"],
                        snapshot_id=row["snapshot_id"],
                        build_id=row["build_id"],
                        commit_sha=row["commit_sha"],
                        release_id=row["release_id"],
                        required_by=row["required_by"],
                        required_by_details=row["required_by_details"],
                        start_date=today,
                        end_date=ACTIVE_END_DATE,
                        source=row["source"],
                        synced_at=now,
                    )
                )
                continue

            same_payload = (
                existing.version == row["version"]
                and (existing.version_spec or None) == (row["version_spec"] or None)
                and (existing.snapshot_id or None) == (row["snapshot_id"] or None)
                and (existing.build_id or None) == (row["build_id"] or None)
                and (existing.commit_sha or None) == (row["commit_sha"] or None)
                and existing.release_id == row["release_id"]
                and (existing.required_by or None) == (row["required_by"] or None)
                and (existing.required_by_details or None) == (row["required_by_details"] or None)
                and (existing.source or None) == (row["source"] or None)
            )
            if same_payload:
                existing.synced_at = now
                continue

            if existing.start_date == today:
                existing.version = row["version"]
                existing.version_spec = row["version_spec"]
                existing.snapshot_id = row["snapshot_id"]
                existing.build_id = row["build_id"]
                existing.commit_sha = row["commit_sha"]
                existing.release_id = row["release_id"]
                existing.required_by = row["required_by"]
                existing.required_by_details = row["required_by_details"]
                existing.source = row["source"]
                existing.synced_at = now
                continue

            existing.end_date = today
            existing.synced_at = now
            session.add(
                Package(
                    name=row["name"],
                    service_name=row["service_name"],
                    version=row["version"],
                    version_spec=row["version_spec"],
                    package_type=row["package_type"],
                    snapshot_id=row["snapshot_id"],
                    build_id=row["build_id"],
                    commit_sha=row["commit_sha"],
                    release_id=row["release_id"],
                    required_by=row["required_by"],
                    required_by_details=row["required_by_details"],
                    start_date=today,
                    end_date=ACTIVE_END_DATE,
                    source=row["source"],
                    synced_at=now,
                )
            )

        for key, existing in current_map.items():
            if key in incoming_keys:
                continue
            existing.end_date = today
            existing.synced_at = now

    logger.info(
        "Synced %s packages for %s (%s managed, %s transitive)",
        len(rows),
        SERVICE_NAME,
        sum(1 for row in rows if row["package_type"] == "managed"),
        sum(1 for row in rows if row["package_type"] == "transitive"),
    )
