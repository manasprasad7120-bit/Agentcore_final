from __future__ import annotations

import os


class RabbitMQConfig:
    """Configuration for RabbitMQ connection, read from environment variables.

    RABBITMQ_URL is loaded from Azure Key Vault at startup (via key_vault.py)
    or can be set directly in .env for local development.
    """

    def __init__(self) -> None:
        self.enabled: bool = os.getenv("RABBITMQ_ENABLED", "false").lower() in ("true", "1", "yes")
        self.prefetch_count: int = int(os.getenv("RABBITMQ_PREFETCH_COUNT", "5"))
        # Queue names
        self.build_queue: str = os.getenv("RABBITMQ_BUILD_QUEUE", "agentcore.build")
        self.run_queue: str = os.getenv("RABBITMQ_RUN_QUEUE", "agentcore.run")
        self.schedule_queue: str = os.getenv("RABBITMQ_SCHEDULE_QUEUE", "agentcore.schedule")
        self.trigger_queue: str = os.getenv("RABBITMQ_TRIGGER_QUEUE", "agentcore.trigger")
        self.orchestrator_queue: str = os.getenv("RABBITMQ_ORCHESTRATOR_QUEUE", "agentcore.orchestrator")

    @property
    def host(self) -> str:
        """Host for logging purposes."""
        url = os.getenv("RABBITMQ_URL", "")
        if url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return parsed.hostname or "localhost"
            except Exception:
                return "localhost"
        return os.getenv("RABBITMQ_HOST", "localhost")

    @property
    def port(self) -> int:
        url = os.getenv("RABBITMQ_URL", "")
        if url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return parsed.port or 5672
            except Exception:
                return 5672
        return int(os.getenv("RABBITMQ_PORT", "5672"))

    @property
    def url(self) -> str:
        """RABBITMQ_URL from env (loaded from Key Vault at startup or set directly)."""
        return os.getenv(
            "RABBITMQ_URL",
            f"amqp://{os.getenv('RABBITMQ_USER', 'guest')}:{os.getenv('RABBITMQ_PASSWORD', 'guest')}"
            f"@{os.getenv('RABBITMQ_HOST', 'localhost')}:{os.getenv('RABBITMQ_PORT', '5672')}"
            f"/{os.getenv('RABBITMQ_VHOST', '/')}",
        )
