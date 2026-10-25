"""Azure Key Vault secret client for pinecone-service."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class KeyVaultConfig(BaseModel):
    vault_url: str | None = None
    secret_prefix: str = "agentcore-pinecone"


@dataclass(slots=True)
class KeyVaultSecretStore:
    """Thin wrapper around Azure Key Vault SecretClient."""

    _client: object
    secret_prefix: str

    @classmethod
    def from_config(cls, config: KeyVaultConfig) -> "KeyVaultSecretStore | None":
        if not config.vault_url:
            return None

        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_interactive_browser_credential=True,
        )

        client = SecretClient(
            vault_url=config.vault_url,
            credential=credential,
            retry_total=5,
            retry_connect=3,
            retry_read=3,
            retry_backoff_factor=0.8,
        )
        return cls(_client=client, secret_prefix=config.secret_prefix)

    def get_secret(self, name: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._client.get_secret(name).value
        except ResourceNotFoundError:
            return None
