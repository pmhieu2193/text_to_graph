from abc import ABC, abstractmethod

from app.schemas.extraction import ExtractionPayload


class LLMProviderError(Exception):
    """Base exception for AI provider errors."""


class LLMConfigurationError(LLMProviderError):
    """Missing or invalid provider configuration."""


class LLMTemporaryError(LLMProviderError):
    """Temporary error that may succeed when retried."""


class LLMPermanentError(LLMProviderError):
    """Permanent error that should not be retried."""


class LLMProvider(ABC):

    provider_name: str
    model_name: str

    @abstractmethod
    def validate_configuration(self) -> None:
        """
        Validate credentials and provider settings.
        """

    @abstractmethod
    def extract(self, text: str) -> ExtractionPayload:
        """
        Extract entities and relations from one text chunk.
        """