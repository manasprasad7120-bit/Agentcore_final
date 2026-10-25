#!/usr/bin/env python
"""Compare local Python environment packages vs pyproject.toml and uv.lock.

Usage:
  python scripts/compare_env_deps.py --project agentcore/src/backend
  python scripts/compare_env_deps.py --project agentcore/src/services/model-service
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_NAME_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9._-]*)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_pyproject_deps(pyproject_path: Path) -> set[str]:
    if not pyproject_path.exists():
        return set()

    data = pyproject_path.read_bytes()
    project: dict[str, Any] = {}

    # Prefer stdlib tomllib (py3.11+), fallback to toml if present.
    try:
        import tomllib  # type: ignore[import-not-found]

        project = tomllib.loads(data.decode("utf-8")).get("project", {})  # type: ignore[assignment]
    except Exception:
        try:
            import toml  # type: ignore[import-not-found]

            project = toml.loads(data.decode("utf-8")).get("project", {})  # type: ignore[assignment]
        except Exception:
            project = {}

    deps = project.get("dependencies", []) or []
    names = set()
    for dep in deps:
        dep_clean = str(dep).split(";")[0].strip()
        m = _NAME_RE.match(dep_clean)
        if m:
            names.add(_norm(m.group(1)))
    return names


def _read_uv_lock(pk_path: Path) -> set[str]:
    try:
        data = pk_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()

    names = set()
    for line in data.splitlines():
        if line.strip().startswith("name ="):
            _, _, val = line.partition("=")
            name = val.strip().strip('"').strip("'")
            if name:
                names.add(_norm(name))
    return names


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _get_installed_packages() -> set[str]:
    # Prefer `uv pip list --format=json` if available.
    code, out, _ = _run(["uv", "pip", "list", "--format", "json"])
    if code == 0:
        try:
            data = json.loads(out)
            return {_norm(p["name"]) for p in data if "name" in p}
        except Exception:
            pass

    # Fallback to python -m pip list --format=json
    code, out, _ = _run([sys.executable, "-m", "pip", "list", "--format", "json"])
    if code == 0:
        try:
            data = json.loads(out)
            return {_norm(p["name"]) for p in data if "name" in p}
        except Exception:
            pass

    return set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare env deps vs pyproject/uv.lock")
    parser.add_argument("--project", required=True, help="Path to service folder containing pyproject.toml")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    pyproject = project_dir / "pyproject.toml"
    uv_lock = project_dir / "uv.lock"

    declared = _read_pyproject_deps(pyproject)
    locked = _read_uv_lock(uv_lock)
    installed = _get_installed_packages()

    missing_in_pyproject = installed - declared
    missing_in_env = declared - installed
    missing_in_lock = declared - locked
    missing_in_lock_vs_env = installed - locked

    print(f"Project: {project_dir}")
    print(f"Declared (pyproject): {len(declared)}")
    print(f"Locked (uv.lock):    {len(locked)}")
    print(f"Installed (env):     {len(installed)}")
    print()

    if missing_in_pyproject:
        print("Installed but NOT declared in pyproject.toml:")
        for name in sorted(missing_in_pyproject):
            print(f"  - {name}")
        print()
    else:
        print("OK: No installed packages missing from pyproject.toml.")
        print()

    if missing_in_env:
        print("Declared in pyproject.toml but NOT installed in env:")
        for name in sorted(missing_in_env):
            print(f"  - {name}")
        print()
    else:
        print("OK: All declared packages are installed.")
        print()

    if missing_in_lock:
        print("Declared in pyproject.toml but NOT present in uv.lock:")
        for name in sorted(missing_in_lock):
            print(f"  - {name}")
        print()
    else:
        print("OK: uv.lock includes all declared packages.")
        print()

    if missing_in_lock_vs_env:
        print("Installed in env but NOT present in uv.lock:")
        for name in sorted(missing_in_lock_vs_env):
            print(f"  - {name}")
        print()
    else:
        print("OK: uv.lock covers all installed packages.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
