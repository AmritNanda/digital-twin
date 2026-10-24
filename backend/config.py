"""Centralized configuration using pydantic-settings."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (one level above backend/). All relative paths in .env are
# resolved against this so the server behaves the same regardless of CWD.
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 1
    llm_reasoning_effort: str = "low"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # Search
    tavily_api_key: str = ""
    serpapi_key: str = ""
    demo_mode: bool = False

    # News
    newsapi_key: str = ""

    # Storage
    chroma_persist_dir: str = "./data/chroma"
    database_url: str = "sqlite:///./data/twin.db"
    upload_dir: str = "./data/uploads"
    fixtures_dir: str = "./data/fixtures"

    # Application limits
    port: int = 8000
    max_file_size_mb: int = 20
    max_iterations: int = 12
    max_research_calls: int = 6
    max_llm_calls: int = 40
    case_timeout_seconds: int = 300

    def model_post_init(self, __context) -> None:
        # Anchor relative storage paths to the project root
        for field in ("chroma_persist_dir", "upload_dir", "fixtures_dir"):
            p = Path(getattr(self, field))
            if not p.is_absolute():
                setattr(self, field, str((ROOT_DIR / p).resolve()))

    @property
    def llm_requires_key(self) -> bool:
        """Hosted OpenAI-compatible APIs need a key; local servers (Ollama, LM Studio) don't."""
        local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")
        return not any(h in self.llm_base_url for h in local_hosts)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key) or not self.llm_requires_key


settings = Settings()
