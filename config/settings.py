from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        alias="OLLAMA_BASE_URL",
    )
    llm_model: str = Field(default="mistral", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")

    database_url: str = Field(
        default="sqlite:///./data/pii_pipeline.db",
        alias="DATABASE_URL",
    )
    checkpoint_db_path: str = Field(
        default="./data/checkpoints.db",
        alias="CHECKPOINT_DB_PATH",
    )

    max_graph_steps: int = Field(default=20, alias="MAX_GRAPH_STEPS")
    max_rescan_retries: int = Field(default=2, alias="MAX_RESCAN_RETRIES")
    max_input_chars: int = Field(default=50_000, alias="MAX_INPUT_CHARS")
    escalate_on_low_confidence: bool = Field(
        default=True,
        alias="ESCALATE_ON_LOW_CONFIDENCE",
    )
    pii_confidence_threshold: float = Field(
        default=0.7,
        alias="PII_CONFIDENCE_THRESHOLD",
    )
    pii_entity_types: str = Field(
        default="EMAIL,PHONE,PERSON,ADDRESS,IBAN,CNP,CREDIT_CARD",
        alias="PII_ENTITY_TYPES",
    )
    presidio_enabled: bool = Field(default=True, alias="PRESIDIO_ENABLED")
    presidio_language: str = Field(default="en", alias="PRESIDIO_LANGUAGE")
    llm_soft_detect_enabled: bool = Field(
        default=True,
        alias="LLM_SOFT_DETECT_ENABLED",
    )

    vault_passphrase: str = Field(default="", alias="VAULT_PASSPHRASE")
    artifacts_dir: str = Field(default="./artifacts", alias="ARTIFACTS_DIR")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")
    log_prompts: bool = Field(default=False, alias="LOG_PROMPTS")

    def entity_types(self) -> list[str]:
        return [part.strip().upper() for part in self.pii_entity_types.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
