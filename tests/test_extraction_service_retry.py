import pytest

from app.providers.llm.base import (
    LLMConfigurationError,
    LLMOutputError,
    LLMPermanentError,
    LLMTemporaryError,
)


def test_retry_error_types_are_distinct():
    """
    Đảm bảo các loại lỗi có thể phân biệt.
    """

    assert issubclass(
        LLMOutputError,
        Exception,
    )

    assert issubclass(
        LLMTemporaryError,
        Exception,
    )

    assert issubclass(
        LLMConfigurationError,
        Exception,
    )

    assert issubclass(
        LLMPermanentError,
        Exception,
    )