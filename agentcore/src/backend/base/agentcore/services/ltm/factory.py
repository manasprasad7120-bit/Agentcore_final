from agentcore.services.base import Service
from agentcore.services.factory import ServiceFactory
from agentcore.services.ltm.service import LTMService


class LTMServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(LTMService)

    def create(self) -> Service:
        return LTMService()
