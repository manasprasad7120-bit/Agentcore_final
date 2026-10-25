from agentcore.services.base import Service
from agentcore.services.factory import ServiceFactory
from agentcore.services.rabbitmq.service import RabbitMQService


class RabbitMQServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(RabbitMQService)

    def create(self) -> Service:
        return RabbitMQService()
