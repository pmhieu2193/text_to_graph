import json

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from app.core.config import settings
from app.providers.llm.base import (
    LLMConfigurationError,
    LLMOutputError,
    LLMPermanentError,
    LLMProvider,
    LLMQuotaError,
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
                    timeout=120_000,
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
Bạn là hệ thống trích xuất đồ thị tri thức (KG) từ văn bản tiếng Việt.

**NHIỆM VỤ:**

1. Chỉ trích xuất các thực thể là danh từ riêng hoặc đối tượng cụ thể, có ý nghĩa phù hợp để biểu diễn thành nút trong KG.
2. Trích xuất các mối quan hệ được đề cập rõ ràng trong văn bản.
3. Gom cụm và chuẩn hóa các thực thể cùng chỉ một đối tượng. Ví dụ: "Hà Nội" và "Thủ đô Hà Nội", hoặc các tên viết tắt, biệt danh nếu văn bản xác nhận chúng cùng một thực thể. Chọn một tên đại diện phù hợp và đưa các tên gọi thay thế thực sự vào danh sách `aliases`. Không đưa đại từ, từ chỉ định, mốc thời gian tương đối, danh từ chung, cụm tham chiếu như "dự án này", "thành phố đó", vai trò, chức danh hoặc mô tả vào `aliases`. Chỉ gộp khi có đủ căn cứ từ văn bản; nếu không chắc chắn, giữ riêng. Thực thể đại diện kế thừa toàn bộ quan hệ của các thực thể được gộp; sau khi gộp, cập nhật các tham chiếu và loại bỏ quan hệ trùng lặp.
4. Không tự suy diễn hoặc tạo thực thể, quan hệ không có căn cứ trong văn bản.
5. Giữ nguyên ý nghĩa và tên gọi thực thể theo nguồn; không tự ý thay đổi nội dung.
6. Loại thực thể sử dụng tên ngắn gọn, nhất quán theo Schema.org (Person, Organization, Place, Event, Product,...). `relation_type` sử dụng định dạng UPPER_SNAKE_CASE, có dấu tiếng Việt.
7. `evidence` của thực thể là danh sách các đoạn trích nguyên văn từ nguồn. `confidence` nằm trong khoảng 0–1.

**QUY TẮC RELATION:**
- `subject_local_id` và `object_local_id` phải tham chiếu đến các `local_id` tồn tại trong danh sách entities.
- Quan hệ phải có hướng rõ ràng, `relation_type` ngắn gọn và thể hiện đúng bản chất quan hệ.
- Không tạo quan hệ có tham chiếu đến thực thể không tồn tại.

Nếu không có thực thể hoặc quan hệ phù hợp, trả về danh sách rỗng tương ứng.

**VĂN BẢN NGUỒN:**

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