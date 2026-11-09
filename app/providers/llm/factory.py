from app.core.config import settings

from app.providers.llm.base import LLMConfigurationError

from app.providers.llm.gemini import GeminiProvider


def get_llm_provider():

    provider_name = settings.llm_provider.strip().lower()

    if provider_name == "gemini":
        return GeminiProvider()

    raise LLMConfigurationError(
        f"LLM_PROVIDER='{provider_name}' chưa được triển khai. "
        "Hãy tạo provider implement LLMProvider và đăng ký tại factory.py."
    )