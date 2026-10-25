"""Local encrypted secret store: drop-in replacement for Azure Key Vault.

Used when ``MODEL_SERVICE_KEY_VAULT_URL`` is not configured (local demos,
self-hosted deployments without Azure). Secrets are encrypted with Fernet using
``MODEL_SERVICE_ENCRYPTION_KEY`` and kept in a small JSON file. The interface
mirrors :class:`app.utils.key_vault.KeyVaultSecretStore` (``set_secret`` /
``get_secret`` / ``delete_secret``) so the registry code is unchanged.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# <model-service>/.secrets/model-service-secrets.json (git-ignored)
DEFAULT_SECRETS_FILE = Path(__file__).resolve().parents[2] / ".secrets" / "model-service-secrets.json"


def resolve_secrets_file() -> Path:
    configured = (os.getenv("MODEL_SERVICE_LOCAL_SECRETS_FILE") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_SECRETS_FILE


@dataclass
class LocalEncryptedSecretStore:
    """File-backed, Fernet-encrypted name -> secret store."""

    encryption_key: str
    path: Path = field(default_factory=resolve_secrets_file)
    source_label: str = "local_encrypted"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _fernet(self) -> Fernet:
        try:
            return Fernet(self.encryption_key.encode())
        except (ValueError, TypeError) as exc:
            msg = (
                "MODEL_SERVICE_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
            raise RuntimeError(msg) from exc

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def set_secret(self, name: str, value: str, *, tags: dict[str, str] | None = None) -> None:  # noqa: ARG002
        token = self._fernet().encrypt(value.encode("utf-8")).decode("ascii")
        with self._lock:
            data = self._load()
            data[name] = token
            self._save(data)

    def get_secret(self, name: str) -> str | None:
        with self._lock:
            token = self._load().get(name)
        if not token:
            return None
        try:
            return self._fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None

    def delete_secret(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if name in data:
                del data[name]
                self._save(data)
