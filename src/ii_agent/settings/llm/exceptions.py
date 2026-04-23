"""LLM settings domain exceptions."""

from ii_agent.core.exceptions import NotFoundError
from ii_agent.core.exceptions import ValidationError
from ii_agent.settings.llm.types import ModelAvailabilityStatus


class LLMSettingNotFoundError(NotFoundError):
    """Raised when an LLM setting is not found or access is denied."""

    pass


class LLMSettingUnavailableError(ValidationError):
    """Raised when a model setting exists but cannot be executed."""

    def __init__(
        self,
        message: str,
        *,
        availability_status: ModelAvailabilityStatus = ModelAvailabilityStatus.MISSING_CREDENTIALS,
    ) -> None:
        self.availability_status = availability_status
        super().__init__(message)
