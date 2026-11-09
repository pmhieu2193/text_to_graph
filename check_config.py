from app.core.config import settings

print("Provider:", settings.llm_provider)
print("Model:", settings.llm_model)
print("API key configured:", bool(settings.llm_api_key))
print("API key length:", len(settings.llm_api_key or ""))