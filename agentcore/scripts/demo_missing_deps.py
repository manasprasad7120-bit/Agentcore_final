"""Print declared project dependencies that are not installed in the current interpreter.

Used by start-demo.ps1 after `uv sync --frozen`: the lockfiles in this repo can lag
behind pyproject.toml, so anything declared but missing is installed afterwards.

Usage:  <venv python> scripts/demo_missing_deps.py <path/to/pyproject.toml>
Output: one requirement specifier per line (empty output = nothing missing).
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path


def _name_of(spec: str) -> str:
    return re.split(r"[\s\[<>=!~;@]", spec.strip(), maxsplit=1)[0]


def main() -> int:
    pyproject = Path(sys.argv[1] if len(sys.argv) > 1 else "pyproject.toml")
    deps = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
    try:
        from packaging.requirements import Requirement
    except Exception:  # noqa: BLE001
        Requirement = None  # type: ignore[assignment]

    for dep in deps:
        name = _name_of(dep)
        if Requirement is not None:
            try:
                req = Requirement(dep)
                name = req.name
                if req.marker and not req.marker.evaluate():
                    continue
            except Exception:  # noqa: BLE001
                pass
        elif ";" in dep:
            marker = dep.split(";", 1)[1]
            if "python_version" in marker and ">=" in marker and "3.13" in marker:
                continue  # only needed on newer Pythons
        try:
            md.distribution(name)
        except md.PackageNotFoundError:
            print(dep.split(";")[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
