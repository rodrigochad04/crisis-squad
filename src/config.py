"""Application-wide configuration via pydantic-settings.

All values are read from environment variables (or .env).
Import `settings` anywhere — it is a module-level singleton.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────────────────────
    llm_model: str = "groq/qwen/qwen3.6-27b"
    llm_fast_model: str = "groq/qwen/qwen3.6-27b"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096
    llm_timeout_seconds: float = 45.0
    # Base URL for OpenAI-compatible endpoints (LiteLLM proxy, vLLM, Azure ...).
    # Leave empty to use the provider default.
    llm_base_url: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""

    # ── LangSmith tracing ──────────────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "gcb-crisis-squad"

    # ── Instana ────────────────────────────────────────────────────────────
    instana_base_url: str = "https://your-instance.instana.io"
    instana_api_token: str = ""

    # ── Jira ───────────────────────────────────────────────────────────────
    jira_base_url: str = "https://your-org.atlassian.net"
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "KAN"

    # ── Microsoft Teams ────────────────────────────────────────────────────
    teams_tenant_id: str = ""
    teams_client_id: str = ""
    teams_client_secret: str = ""
    teams_team_id: str = ""
    teams_oncall_emails: str = ""

    # ── Knowledge base ─────────────────────────────────────────────────────
    kb_docs_dir: str = "./docs/runbooks"
    kb_persist_dir: str = "./data/faiss_index"

    # ── HitL webhook ───────────────────────────────────────────────────────
    hitl_webhook_url: str = ""

    # ── Demo / development ─────────────────────────────────────────────────
    demo_mode: bool = False  # True → all external APIs are mocked

    # ── API ────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "change-me-in-production"
    # When true, mutating endpoints (/incidents, /approve) require a bearer token
    # equal to api_secret_key. Defaults to on for anything that is not demo mode.
    api_auth_enabled: bool = True
    # Shown in the dashboard footer. Set REPO_URL after forking so the link
    # points at your repository rather than a hard-coded one.
    repo_url: str = "https://github.com/your-org/crisis-squad"
    # Comma-separated list of allowed browser origins for the dashboard.
    cors_allow_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
