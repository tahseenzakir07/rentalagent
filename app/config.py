import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Rentaliq operational settings."""

    # Application identity
    app_name: str = "Rentaliq - AI Equipment Rental Decision Agent"
    app_version: str = "0.1.0"
    debug: bool = False

    # Execution Mode: LLM is standard/mandatory; SIMULATED is only used as offline fallback if no key is configured yet
    execution_mode: str = Field(
        default_factory=lambda: "LLM" if (
            os.getenv("RENTALIQ_LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        ) else "LLM",
        validation_alias="RENTALIQ_EXECUTION_MODE",
    )
    llm_provider: str = Field(
        default_factory=lambda: "gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else (
            "openai" if os.getenv("OPENAI_API_KEY") else "gemini"
        ),
        validation_alias="RENTALIQ_LLM_PROVIDER",
    )
    llm_api_key: str = Field(
        default_factory=lambda: (
            os.getenv("RENTALIQ_LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ),
        validation_alias="RENTALIQ_LLM_API_KEY",
    )
    llm_model: str = Field(
        default_factory=lambda: "gemini-1.5-flash" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else "gpt-4o-mini",
        validation_alias="RENTALIQ_LLM_MODEL",
    )

    # Orchestrator parameters
    max_iterations: int = Field(default=5, validation_alias="RENTALIQ_MAX_ITERATIONS")
    min_confidence_for_auto: float = Field(default=0.70, validation_alias="RENTALIQ_MIN_CONFIDENCE_FOR_AUTO")
    min_qualification_score: float = Field(default=85.0, validation_alias="RENTALIQ_MIN_QUALIFICATION_SCORE")

    # Persistence & Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    sqlite_db_path: Path = Path(__file__).resolve().parent.parent / "rentaliq.db"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def set_api_key(self, api_key: str, provider: str = "auto", model: str = "") -> None:
        """Update runtime API key configuration globally for all users."""
        clean_key = api_key.strip()
        self.llm_api_key = clean_key
        
        # Auto-detect provider if needed
        if provider == "auto" or not provider:
            if clean_key.startswith("AIza"):
                self.llm_provider = "gemini"
            elif clean_key.startswith("sk-"):
                self.llm_provider = "openai"
            else:
                self.llm_provider = "gemini" if "gemini" in self.llm_provider else "openai"
        else:
            self.llm_provider = provider

        # Default model based on provider if not explicitly given
        if model:
            self.llm_model = model.strip()
        else:
            if self.llm_provider == "gemini":
                self.llm_model = "gemini-1.5-flash"
            elif self.llm_provider == "openai":
                self.llm_model = "gpt-4o-mini"
            else:
                self.llm_model = "gpt-4o-mini"

        self.execution_mode = "LLM" if self.llm_api_key else "SIMULATED"


settings = Settings()
