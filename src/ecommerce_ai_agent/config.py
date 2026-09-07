from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ecommerce-ai-agent"
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecommerce_agent"
    postgres_user: str = "ecommerce"
    postgres_password: SecretStr

    redis_host: str = "localhost"
    redis_port: int = 6379

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_management_port: int = 9091

    healthcheck_timeout_seconds: float = 3.0

    dashscope_api_key: SecretStr | None = None
    bailian_base_url: AnyHttpUrl | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_max_completion_tokens: int = Field(default=800, ge=1, le=8192)

    embedding_model: str = Field(default="text-embedding-v4", min_length=1)
    embedding_dimensions: int = Field(default=1024, ge=64, le=2048)
    knowledge_collection: str = Field(
        default="ecommerce_knowledge",
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    knowledge_top_k: int = Field(default=3, ge=1, le=10)
    bailian_rerank_base_url: AnyHttpUrl | None = None
    rerank_model: str = Field(default="qwen3-rerank", min_length=1)
    hybrid_candidate_k: int = Field(default=10, ge=2, le=50)
    rrf_k: float = Field(default=60, gt=0, le=16384)
    rerank_min_score: float = Field(default=0.2, ge=0, le=1)

    # Temporary trusted identity for local M4 verification; JWT will replace it later.
    development_user_email: str = Field(default="alice@example.com", min_length=3)
