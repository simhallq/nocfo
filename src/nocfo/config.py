"""Configuration loading and validation."""

import functools
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    fortnox_client_id: str = Field(default="", description="Fortnox OAuth2 client ID")
    fortnox_client_secret: str = Field(default="", description="Fortnox OAuth2 client secret")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for web agent")
    database_path: Path = Field(default=Path("data/nocfo.db"), description="SQLite database path")
    log_level: str = Field(default="INFO", description="Logging level")
    fortnox_base_url: str = Field(
        default="https://api.fortnox.se/3", description="Fortnox API base URL"
    )
    fortnox_auth_url: str = Field(
        default="https://apps.fortnox.se/oauth-v1", description="Fortnox OAuth URL"
    )
    oauth_redirect_uri: str = Field(
        default="http://localhost:8888/callback", description="OAuth redirect URI"
    )
    oauth_redirect_port: int = Field(default=8888, description="OAuth redirect server port")
    workflows_dir: Path = Field(
        default=Path("data/workflows"), description="Directory for recorded workflow YAML files"
    )

    # Browser API settings
    browser_api_url: str = Field(
        default="http://localhost:8790", description="Browser API server URL"
    )
    browser_api_token: str = Field(default="", description="Browser API bearer token")
    browser_cdp_port: int = Field(default=9222, description="Chrome CDP port")
    browser_profile_dir: Path = Field(
        default=Path("data/browser_profile"), description="Chrome user data directory"
    )

    # Vision fallback & evidence settings
    vision_fallback_enabled: bool = Field(
        default=True, description="Enable Claude vision fallback for selector discovery"
    )
    screenshots_dir: Path = Field(
        default=Path("data/screenshots"), description="Directory for evidence screenshots"
    )
    learned_selectors_path: Path = Field(
        default=Path("data/learned_selectors.json"), description="Path to learned selectors store"
    )

    # BankID auth settings
    funnel_base: str = Field(default="", description="Tailscale Funnel base URL for BankID QR")
    sessions_dir: Path = Field(
        default=Path("data/sessions"), description="Per-customer session cookies"
    )

    def validate_fortnox_credentials(self) -> bool:
        """Check that Fortnox credentials are configured."""
        return bool(self.fortnox_client_id and self.fortnox_client_secret)

    def validate_anthropic_key(self) -> bool:
        """Check that Anthropic API key is configured."""
        return bool(self.anthropic_api_key)


@functools.lru_cache
def get_settings() -> Settings:
    """Load and return application settings (cached singleton)."""
    return Settings()
