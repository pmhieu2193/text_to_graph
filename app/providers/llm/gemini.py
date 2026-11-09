import json
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from app.core.config import settings
from app.providers.llm.base import (
    LLMConfigurationError,
    LLMPermanentError,
    LLMProvider,
    LLMTemporaryError,
)
from app.schemas.extraction import ExtractionPayload


def clean_schema_for_gemini(data):
    """
    Đệ quy loại bỏ các trường metadata và constraints gây quá tải 
    trình biên dịch Schema (FSM State Limit) của Gemini API.
    """
    if isinstance(data, dict):
        # Các key gây bùng nổ không gian trạng thái FSM trong Gemini API
        unsupported_keys = {
            # Metadata
            "title", "description", "examples", "default", "$schema", 
            "additionalProperties", "additional_properties",
            # Validation Constraints (Nguyên nhân chính gây quá tải state)
            "minimum", "maximum", "minLength", "maxLength", 
            "pattern", "format", "minItems", "maxItems", "uniqueItems", "multipleOf"
        }
        return {
            k: clean_schema_for_gemini(v)
            for k, v in data.items()
            if k not in unsupported_keys
        }
    elif isinstance(data, list):
        return [clean_schema_for_gemini(item) for item in data]
    return data


class GeminiProvider(LLMProvider):

    provider_name = "gemini"

    def __init__(self):
        self.model_name = settings.llm_model
        self._client = None

    def validate_configuration(self) -> None:
        if not settings.llm_api_key:
            raise LLMConfigurationError(
                "LLM_API_KEY chưa được cấu hình trong file .env."
            )

        if not self.model_name:
            raise LLMConfigurationError(
                "LLM_MODEL không được để trống."
            )

    @property
    def client(self):
        if self._client is None:
            self.validate_configuration()

            self._client = genai.Client(
                api_key=settings.llm_api_key,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(
                        attempts=1,
                    ),
                ),
            )
        return self._client

    @staticmethod
    def build_prompt(text: str) -> str:
        return f"""
Bạn là hệ thống trích xuất đồ thị tri thức từ văn bản tiếng Việt.

NHIỆM VỤ:

1. Trích xuất các thực thể có ý nghĩa trong văn bản.
2. Trích xuất các mối quan hệ được đề cập rõ ràng.
3. Không tự suy diễn thông tin không xuất hiện trong văn bản.
4. Không tạo thực thể hoặc quan hệ chỉ vì chúng có vẻ hợp lý.
5. Tên thực thể phải giữ nguyên ý nghĩa và tên gọi trong nguồn.
6. Loại thực thể nên ngắn gọn, nhất quán.
7. Evidence phải là đoạn trích nguyên văn từ văn bản nguồn.
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
            # Sinh JSON schema nguyên bản từ Pydantic và lọc sạch triệt để
            raw_schema = ExtractionPayload.model_json_schema()
            gemini_schema = clean_schema_for_gemini(raw_schema)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self.build_prompt(text),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=gemini_schema,
                ),
            )

            # Ưu tiên lấy dữ liệu đã parse
            parsed = getattr(response, "parsed", None)

            if isinstance(parsed, ExtractionPayload):
                return parsed

            if parsed is not None:
                return ExtractionPayload.model_validate(parsed)

            # Fallback parse từ string response.text
            response_text = getattr(response, "text", None)

            if not response_text:
                raise LLMPermanentError(
                    "Gemini trả về response rỗng."
                )

            return ExtractionPayload.model_validate_json(response_text)

        except (LLMPermanentError, LLMTemporaryError):
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

            if status_code in {408, 429, 500, 502, 503, 504}:
                raise LLMTemporaryError(
                    f"Gemini API tạm thời không khả dụng "
                    f"(HTTP {status_code}): {exc}"
                ) from exc

            raise LLMPermanentError(
                f"Gemini API error (HTTP {status_code}): {exc}"
            ) from exc

        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise LLMPermanentError(
                f"Không thể parse hoặc validate response: {exc}"
            ) from exc

        except (TimeoutError, ConnectionError) as exc:
            raise LLMTemporaryError(
                f"Kết nối Gemini thất bại: {exc}"
            ) from exc

        except Exception as exc:
            raise LLMPermanentError(
                f"Lỗi Gemini không phân loại: {exc}"
            ) from exc