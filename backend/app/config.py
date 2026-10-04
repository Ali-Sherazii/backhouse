from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://backhouse:backhouse@localhost:5432/backhouse"
    redis_url: str = "redis://localhost:6379/1"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "backhouse"
    minio_secret_key: str = "backhouse"
    minio_secure: bool = False
    minio_bucket: str = "invoices"
    langfuse_bucket: str = "langfuse"

    jwt_secret: str = "dev-secret"
    jwt_ttl_hours: int = 12
    webhook_secret: str = "dev-webhook-secret"
    demo_password: str = "demo1234"

    auto_approve_min_confidence: float = 0.85
    max_upload_mb: int = 15

    app_public_url: str = "http://localhost:3000"
    api_internal_url: str = "http://api:8000"
    n8n_export_webhook_url: str = "http://n8n:5678/webhook/backhouse-export"
    odoo_public_url: str = "http://localhost:8069"

    llm_provider: str = "ollama"  # ollama | openai
    llm_base_url: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:3b"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 300

    hf_token: str = ""
    prompt_guard_model: str = "meta-llama/Llama-Prompt-Guard-2-86M"
    guard_ocr_diff: bool = True
    ocr_engine: str = "docling"  # docling | paddle | none

    langfuse_host: str = ""
    langfuse_public_url: str = ""
    langfuse_project_id: str = "backhouse"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    samples_dir: str = "../samples"

    # Text-layer pages need at least this many non-whitespace characters to skip OCR.
    text_layer_min_chars: int = 40
    page_render_dpi: int = 150


@lru_cache
def get_settings() -> Settings:
    return Settings()
