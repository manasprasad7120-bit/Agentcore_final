#!/usr/bin/env python
"""Seed Azure Key Vault secrets from a master file (no .env dependency).

Usage:
  python scripts/seed_keyvault.py --master-file ./keyvault_master.env
  python scripts/seed_keyvault.py --master-file ./keyvault_master.env --vault-url https://<vault>.vault.azure.net/

The script:
  - Reads secret name/value pairs from --master-file
  - Writes them directly to Key Vault
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def _required(value: str | None, message: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(message)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Azure Key Vault secrets using Managed Identity.")
    parser.add_argument("--master-file", required=True)
    parser.add_argument("--vault-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    master_env = _load_env_file(Path(args.master_file))

    vault_url = args.vault_url or os.getenv("AGENTCORE_KEY_VAULT_URL") or master_env.get("KEY_VAULT_URL", "")
    vault_url = _required(vault_url, "Key Vault URL is required.")

    # Collect secrets
    to_seed: list[tuple[str, str]] = []
    for key, value in master_env.items():
        if key == "KEY_VAULT_URL":
            continue
        if not key:
            continue
        value = _required(value, f"Secret value missing for '{key}'.")
        to_seed.append((key, value))

    if not to_seed:
        raise ValueError("No secrets found.")

    if args.dry_run:
        print("Dry run:")
        for name, _ in to_seed:
            print(f"  - {name}")
        return 0

    # ✅ Managed Identity / Default Credential
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential(
        exclude_interactive_browser_credential=True
    )

    client = SecretClient(vault_url=vault_url, credential=credential)

    for name, value in to_seed:
        client.set_secret(name, value)
        print(f"Wrote secret: {name}")

    print("✅ Key Vault seeding complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())