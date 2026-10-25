import os

from loguru import logger

from .service import StorageService


class AzureBlobStorageService(StorageService):
    """A service class for handling Azure Blob Storage operations."""

    def __init__(self, session_service, settings_service) -> None:
        super().__init__(session_service, settings_service)

        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "").strip().strip("'\"")
        self.container_name = os.environ.get(
            "AZURE_STORAGE_CONTAINER_NAME", "agentcore-knowledge-container"
        ).strip().strip("'\"")

        if not account_url:
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_URL is required when STORAGE_TYPE=azure."
            )

        try:
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError:
            raise ImportError(
                "azure-storage-blob package is required for Azure storage. "
                "Install it with: pip install azure-storage-blob"
            )

        self._credential = None
        from azure.identity.aio import DefaultAzureCredential

        # Use the same managed identity chain used by Redis and Key Vault.
        self._credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_interactive_browser_credential=True,
        )
        self._blob_service_client = BlobServiceClient(
            account_url=account_url,
            credential=self._credential,
        )
        logger.info("Azure Blob auth mode: managed identity (AZURE_STORAGE_ACCOUNT_URL)")
        self._container_ensured = False
        self.set_ready()

    def _get_container_client(self):
        return self._blob_service_client.get_container_client(self.container_name)

    def build_full_path(self, agent_id: str, file_name: str) -> str:
        return f"{agent_id}/{file_name}"

    async def _ensure_container_exists(self):
        if self._container_ensured:
            return
        container_client = self._get_container_client()
        try:
            await container_client.get_container_properties()
        except Exception:
            await container_client.create_container()
            logger.info(f"Created Azure blob container: {self.container_name}")
        self._container_ensured = True

    async def save_file(self, agent_id: str, file_name: str, data: bytes) -> None:
        await self._ensure_container_exists()
        blob_path = self.build_full_path(str(agent_id), file_name)
        container_client = self._get_container_client()
        blob_client = container_client.get_blob_client(blob_path)

        try:
            await blob_client.upload_blob(data, overwrite=True)
            logger.info(f"File {file_name} saved to Azure blob in agent {agent_id}.")
        except Exception:
            logger.exception(f"Error saving file {file_name} to Azure blob in agent {agent_id}")
            raise

    async def get_file(self, agent_id: str, file_name: str) -> bytes:
        blob_path = self.build_full_path(str(agent_id), file_name)
        container_client = self._get_container_client()
        blob_client = container_client.get_blob_client(blob_path)

        try:
            stream = await blob_client.download_blob()
            content = await stream.readall()
            logger.debug(f"File {file_name} retrieved from Azure blob in agent {agent_id}.")
            return content
        except Exception as e:
            if "BlobNotFound" in str(e):
                msg = f"File {file_name} not found in agent {agent_id}"
                raise FileNotFoundError(msg) from e
            raise

    async def list_files(self, agent_id: str) -> list[str]:
        if not isinstance(agent_id, str):
            agent_id = str(agent_id)

        await self._ensure_container_exists()
        container_client = self._get_container_client()
        prefix = f"{agent_id}/"
        files = []

        async for blob in container_client.list_blobs(name_starts_with=prefix):
            name = blob.name[len(prefix):]
            if name:
                files.append(name)

        logger.info(f"Listed {len(files)} files in agent {agent_id} from Azure blob.")
        return files

    async def get_file_size(self, agent_id: str, file_name: str):
        blob_path = self.build_full_path(str(agent_id), file_name)
        container_client = self._get_container_client()
        blob_client = container_client.get_blob_client(blob_path)

        try:
            properties = await blob_client.get_blob_properties()
            return properties.size
        except Exception as e:
            if "BlobNotFound" in str(e):
                msg = f"File {file_name} not found in agent {agent_id}"
                raise FileNotFoundError(msg) from e
            raise

    async def delete_file(self, agent_id: str, file_name: str) -> None:
        blob_path = self.build_full_path(str(agent_id), file_name)
        container_client = self._get_container_client()
        blob_client = container_client.get_blob_client(blob_path)

        try:
            await blob_client.delete_blob()
            logger.info(f"File {file_name} deleted from Azure blob in agent {agent_id}.")
        except Exception as e:
            if "BlobNotFound" in str(e):
                logger.warning(
                    f"Attempted to delete non-existent file {file_name} in agent {agent_id}."
                )
            else:
                raise

    async def teardown(self) -> None:
        await self._blob_service_client.close()
        close_credential = getattr(self._credential, "close", None)
        if callable(close_credential):
            await close_credential()
