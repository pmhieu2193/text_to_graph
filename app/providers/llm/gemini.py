import json

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from app.core.config import settings
from app.providers.llm.base import (
    LLMConfigurationError,
    LLMOutputError,
    LLMQuotaError,
    LLMPermanentError,
    LLMProvider,
    LLMTemporaryError,
)
from app.schemas.extraction import ExtractionPayload


def clean_schema_for_gemini(data):
    """
    Loại bỏ metadata và constraints không cần thiết
    khỏi JSON Schema trước khi gửi Gemini.
    """
    if isinstance(data, dict):
        unsupported_keys = {
            "title",
            "description",
            "examples",
            "default",
            "$schema",
            "additionalProperties",
            "additional_properties",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "pattern",
            "format",
            "minItems",
            "maxItems",
            "uniqueItems",
            "multipleOf",
        }

        return {
            key: clean_schema_for_gemini(value)
            for key, value in data.items()
            if key not in unsupported_keys
        }

    if isinstance(data, list):
        return [
            clean_schema_for_gemini(item)
            for item in data
        ]

    return data


class GeminiProvider(LLMProvider):

    provider_name = "gemini"

    def __init__(self):
        self.model_name = settings.llm_model

        self._primary_key = settings.llm_api_key
        self._fallback_key = settings.llm_fallback_api_key

        self._active_key = self._primary_key
        self._using_fallback = False

        self._client = None

    def validate_configuration(self) -> None:

        if not self._primary_key:
            raise LLMConfigurationError(
                "LLM_API_KEY chưa được cấu hình."
            )

        if not self.model_name:
            raise LLMConfigurationError(
                "LLM_MODEL không được để trống."
            )

    @property
    def has_fallback_key(self) -> bool:
        return bool(
            self._fallback_key
            and not self._using_fallback
        )

    @property
    def using_fallback_key(self) -> bool:
        return self._using_fallback

    @property
    def client(self):

        if self._client is None:

            if not self._active_key:
                raise LLMConfigurationError(
                    "Không có API key Gemini khả dụng."
                )

            self._client = genai.Client(
                api_key=self._active_key,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(
                        attempts=1,
                    ),
                ),
            )

        return self._client

    def switch_to_fallback_key(self) -> bool:
        """
        Chuyển sang fallback key đúng một lần.

        Trả về False nếu không có key dự phòng
        hoặc key dự phòng đã được sử dụng.
        """

        if not self.has_fallback_key:
            return False

        self._active_key = self._fallback_key
        self._using_fallback = True

        # Client cũ chứa primary key.
        # Tạo client mới ở lần gọi tiếp theo.
        self._client = None

        return True

    @staticmethod
    def _is_quota_error(
        status_code: int | None,
        message: str,
    ) -> bool:

        message = message.lower()

        quota_keywords = (
            "quota exceeded",
            "quota_exceeded",
            "billing",
            "billing not enabled",
            "resource_exhausted",
            "per day",
            "daily limit",
            "insufficient quota",
            "limit: 0",
        )

        # 429 không đồng nghĩa với quota.
        # Chỉ phân loại quota khi nội dung lỗi có dấu hiệu rõ.
        return (
            status_code in {403, 429}
            and any(
                keyword in message
                for keyword in quota_keywords
            )
        )

    @staticmethod
    def _is_invalid_credential(
        status_code: int | None,
        message: str,
    ) -> bool:

        message = message.lower()

        credential_keywords = (
            "api key not valid",
            "invalid api key",
            "api_key_invalid",
            "permission denied",
            "api key expired",
        )

        return (
            status_code in {400, 401, 403}
            and any(
                keyword in message
                for keyword in credential_keywords
            )
        )

    @staticmethod
    def build_prompt(text: str) -> str:

        return f"""
Bạn là hệ thống trích xuất đồ thị tri thức từ văn bản tiếng Việt.

NHIỆM VỤ:

1. Trích xuất các thực thể thực sự có ý nghĩa và quan trọng trong văn bản.
2. Trích xuất các mối quan hệ được đề cập rõ ràng.
3. Hãy gom cụm thực thể trùng lặp và quan hệ của chúng nếu có thể (ví dụ: cụm "Hà Nội", "Thủ đô Hà Nội" và "TP Hà Nội" hoặc cụm "Bác Hồ" và "Hồ Chí Minh" thì mỗi cụm có thể được gom thành một thực thể đại diện duy nhất kế thừa các quan hệ trỏ đến hoặc đi).
4. Không tự suy diễn thông tin hay tạo quan hệ hoặc thực thể không xuất hiện trong văn bản chỉ vì chúng có vẻ hợp lý.
5. Tên thực thể phải giữ nguyên ý nghĩa và tên gọi trong nguồn.
6. Loại thực thể nên ngắn gọn, nhất quán theo tiêu chuẩn Schema.org (Ví dụ: Person, Organization, Place, Event, Product,...), loại quan hệ định dạng UPPER_SNAKE_CASE tiếng Việt có dấu.
7. Evidence phải là đoạn trích nguyên văn từ văn bản nguồn, nếu là enity được gộp thì nội dung Evidence sẽ phân chia bằng dấu ;.
8. Confidence nằm trong khoảng từ 0 đến 1.
QUY TẮC RELATION:

- subject_local_id phải trỏ đến một entity.
- object_local_id phải trỏ đến một entity.
- Không được tham chiếu entity không tồn tại.
- Relation phải có hướng rõ ràng.
- relation_type nên ngắn gọn và thể hiện bản chất quan hệ.

Nếu văn bản không có thực thể hoặc quan hệ phù hợp,
hãy trả về danh sách rỗng tương ứng.

VĂN BẢN NGUỒN:

<source>
{text}
</source>
"""

    def extract(self, text: str) -> ExtractionPayload:

        self.validate_configuration()

        if not text or not text.strip():
            return ExtractionPayload()

        try:

            raw_schema = ExtractionPayload.model_json_schema()

            gemini_schema = clean_schema_for_gemini(
                raw_schema
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self.build_prompt(text),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=gemini_schema,
                ),
            )

            parsed = getattr(
                response,
                "parsed",
                None,
            )

            if isinstance(parsed, ExtractionPayload):
                return parsed

            if parsed is not None:
                try:
                    return ExtractionPayload.model_validate(
                        parsed
                    )
                except ValidationError as exc:
                    raise LLMOutputError(
                        f"Gemini output không đúng schema: {exc}"
                    ) from exc

            response_text = getattr(
                response,
                "text",
                None,
            )

            if not response_text:
                raise LLMOutputError(
                    "Gemini trả về response rỗng."
                )

            try:
                return ExtractionPayload.model_validate_json(
                    response_text
                )

            except (
                json.JSONDecodeError,
                ValidationError,
                TypeError,
            ) as exc:

                raise LLMOutputError(
                    f"Không thể parse hoặc validate Gemini output: {exc}"
                ) from exc

        except (
            LLMOutputError,
            LLMConfigurationError,
            LLMQuotaError,
            LLMTemporaryError,
            LLMPermanentError,
        ):
            raise

        except APIError as exc:

            status_code = (
                getattr(exc, "code", None)
                or getattr(exc, "status_code", None)
            )

            try:
                status_code = int(status_code)
            except (TypeError, ValueError):
                status_code = None

            message = str(exc)

            if self._is_invalid_credential(
                status_code,
                message,
            ):
                raise LLMConfigurationError(
                    f"Gemini API key không hợp lệ: {message}"
                ) from exc

            if self._is_quota_error(
                status_code,
                message,
            ):
                raise LLMQuotaError(
                    f"Gemini quota/billing error: {message}"
                ) from exc

            if status_code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }:
                raise LLMTemporaryError(
                    f"Gemini API tạm thời không khả dụng "
                    f"(HTTP {status_code}): {message}"
                ) from exc

            raise LLMPermanentError(
                f"Gemini API error (HTTP {status_code}): {message}"
            ) from exc

        except (
            TimeoutError,
            ConnectionError,
        ) as exc:

            raise LLMTemporaryError(
                f"Kết nối Gemini thất bại: {exc}"
            ) from exc

        except Exception as exc:

            raise LLMPermanentError(
                f"Lỗi Gemini không phân loại: {exc}"
            ) from exc