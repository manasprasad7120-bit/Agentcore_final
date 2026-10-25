from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _parse_pyproject(pyproject_path: Path) -> list[dict[str, str]]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps: list[str] = data.get("project", {}).get("dependencies", [])
    result: list[dict[str, str]] = []
    for dep in deps:
        clean = dep.split(";")[0].strip()
        match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9._-]*)(.*)", clean)
        if not match:
            continue
        result.append(
            {
                "name": match.group(1).strip().lower(),
                "version_spec": match.group(2).strip() or None,
            }
        )
    return result


def _parse_uv_lock(uv_lock_path: Path) -> list[dict[str, Any]]:
    data = tomllib.loads(uv_lock_path.read_text(encoding="utf-8"))
    packages = data.get("package", [])
    if not isinstance(packages, list):
        return []
    return packages


def build_snapshot(
    *,
    service_name: str,
    pyproject_path: Path,
    uv_lock_path: Path,
    snapshot_id: str | None,
    build_id: str | None,
    commit_sha: str | None,
) -> dict[str, Any]:
    declared = _parse_pyproject(pyproject_path)
    locked = _parse_uv_lock(uv_lock_path)

    if not locked:
        raise ValueError(f"No package entries found in {uv_lock_path}")

    declared_names = {_normalize(dep["name"]) for dep in declared}
    lock_by_name = {_normalize(pkg["name"]): pkg for pkg in locked if "name" in pkg}

    required_by_details_map: dict[str, list[dict[str, str]]] = {}
    for pkg in locked:
        requester_name = (pkg.get("name") or "").strip()
        requester_version = str(pkg.get("version") or "unknown").strip()
        if not requester_name:
            continue
        for dep in pkg.get("dependencies", []):
            dep_name = dep.get("name")
            if not dep_name:
                continue
            dep_norm = _normalize(dep_name)
            required_by_details_map.setdefault(dep_norm, []).append(
                {"name": requester_name, "version": requester_version}
            )

    managed: list[dict[str, Any]] = []
    for dep in declared:
        lock_entry = lock_by_name.get(_normalize(dep["name"]), {})
        managed.append(
            {
                "name": dep["name"],
                "version": str(lock_entry.get("version", "unknown")),
                "version_spec": dep["version_spec"],
                "source": lock_entry.get("source"),
            }
        )

    transitive: list[dict[str, Any]] = []
    for pkg in locked:
        pkg_name = (pkg.get("name") or "").strip()
        if not pkg_name:
            continue
        pkg_norm = _normalize(pkg_name)
        if pkg_norm in declared_names:
            continue
        source = pkg.get("source", {})
        if isinstance(source, dict) and "editable" in source:
            continue
        required_by_details = required_by_details_map.get(pkg_norm, [])
        transitive.append(
            {
                "name": pkg_name,
                "version": str(pkg.get("version", "unknown")),
                "required_by_details": required_by_details,
                "source": source if source else None,
            }
        )

    return {
        "service_name": service_name,
        "snapshot_id": snapshot_id,
        "build_id": build_id,
        "commit_sha": commit_sha,
        "managed": managed,
        "transitive": transitive,
    }


def _post_snapshot(url: str, api_key: str | None, payload: dict[str, Any]) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.getcode(), resp.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export service dependency snapshot from pyproject.toml and uv.lock",
    )
    parser.add_argument("--project", required=True, help="Path to service project directory")
    parser.add_argument("--service-name", required=True, help="Canonical service name (e.g. model-service)")
    parser.add_argument("--snapshot-id", default=None, help="Optional snapshot identifier")
    parser.add_argument("--build-id", default=None, help="Optional CI build identifier")
    parser.add_argument("--commit-sha", default=None, help="Optional commit sha")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Print summary only")
    parser.add_argument("--validate-only", action="store_true", help="Validate inputs and payload shape")
    parser.add_argument("--post-url", default=None, help="Optional API endpoint to POST snapshot JSON")
    parser.add_argument("--api-key", default=None, help="Optional API key for POST")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    pyproject_path = project_dir / "pyproject.toml"
    uv_lock_path = project_dir / "uv.lock"

    if not pyproject_path.exists():
        print(f"ERROR: pyproject.toml not found at {pyproject_path}", file=sys.stderr)
        return 2
    if not uv_lock_path.exists():
        print(f"ERROR: uv.lock not found at {uv_lock_path}", file=sys.stderr)
        return 2

    try:
        payload = build_snapshot(
            service_name=args.service_name.strip().lower(),
            pyproject_path=pyproject_path,
            uv_lock_path=uv_lock_path,
            snapshot_id=args.snapshot_id,
            build_id=args.build_id,
            commit_sha=args.commit_sha,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to build snapshot: {exc}", file=sys.stderr)
        return 1

    managed_count = len(payload["managed"])
    transitive_count = len(payload["transitive"])
    print(
        f"Snapshot OK: service={payload['service_name']} managed={managed_count} transitive={transitive_count}"
    )

    if args.validate_only:
        return 0

    if args.dry_run:
        return 0

    output_json = json.dumps(payload, indent=2)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.write_text(output_json, encoding="utf-8")
        print(f"Wrote snapshot JSON: {out_path}")
    else:
        print(output_json)

    if args.post_url:
        status, response_text = _post_snapshot(args.post_url, args.api_key, payload)
        print(f"POST {args.post_url} -> {status}")
        if response_text:
            print(response_text)
        if status >= 400:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
