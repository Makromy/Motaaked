from typing import Any
from pydantic import Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    MASTER_API_KEY: str = Field("instapay_secret_master_key_2026", validation_alias=AliasChoices("MASTER_API_KEY", "API_KEY"))
    DATABASE_URL: str = Field("sqlite:///./data/instapay.db", validation_alias=AliasChoices("DATABASE_URL", "DB_URL"))
    MATCH_WINDOW_MINUTES: int = 30
    PORTAL_NAME: str = Field("Motaaked", validation_alias=AliasChoices("PORTAL_NAME", "BRAND_NAME"))
    PORTAL_NAME_AR: str = Field("متأكد | Motaaked", validation_alias=AliasChoices("PORTAL_NAME_AR", "BRAND_NAME_AR"))
    # Deployment environment — set to "production" on VPS to enable hardening (Swagger off, key abort)
    ENVIRONMENT: str = Field("development", validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV", "DEPLOY_ENV"))
    # CORS allowed origins — comma-separated list or "*" for all. Default "*" preserves current behavior.
    ALLOWED_ORIGINS: str = Field("*", validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS", "CORS_ALLOWED_ORIGINS"))

    # Demo Mode Sandbox Configuration
    DEMO_MODE_ENABLED: bool = Field(True, validation_alias=AliasChoices("DEMO_MODE_ENABLED", "ENABLE_DEMO_MODE"))
    DEMO_PASSCODE: str = Field("DEMO-SANDBOX-2026", validation_alias=AliasChoices("DEMO_PASSCODE", "DEMO_KEY"))

    # SMTP Email Configuration (Supports both SMTP_* and MAIL_* aliases)
    SMTP_HOST: str = Field("", validation_alias=AliasChoices("SMTP_HOST", "MAIL_HOST", "SMTP_SERVER"))
    SMTP_PORT: int = Field(587, validation_alias=AliasChoices("SMTP_PORT", "MAIL_PORT"))
    SMTP_USER: str = Field("", validation_alias=AliasChoices("SMTP_USER", "MAIL_USERNAME", "MAIL_USER"))
    SMTP_PASSWORD: str = Field("", validation_alias=AliasChoices("SMTP_PASSWORD", "MAIL_PASSWORD", "MAIL_PASS"))
    SMTP_FROM: str = Field("", validation_alias=AliasChoices("SMTP_FROM", "MAIL_FROM_ADDRESS", "MAIL_FROM"))
    SMTP_TLS: bool = Field(True, validation_alias=AliasChoices("SMTP_TLS", "MAIL_ENCRYPTION"))

    @field_validator("SMTP_TLS", mode="before")
    @classmethod
    def parse_smtp_tls(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ["tls", "ssl", "starttls", "true", "1", "yes", "on"]:
                return True
            if clean in ["null", "none", "false", "0", "no", "off", ""]:
                return False
        return bool(v)

    @field_validator("SMTP_PORT", mode="before")
    @classmethod
    def parse_smtp_port(cls, v: Any) -> int:
        if isinstance(v, str):
            clean = v.strip()
            if clean.isdigit():
                return int(clean)
        return int(v) if v is not None else 587

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
