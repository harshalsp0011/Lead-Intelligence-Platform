from __future__ import annotations

"""Central application settings.

This file loads values from the `.env` file and exposes them through one
cached `Settings` object. Almost every part of the project depends on this
module to read API keys, database settings, scraping limits, and feature flags.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Resolve .env relative to this file's parent (project root)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)


class Settings:
    # ------------------------------------------------------------------ #
    # SYSTEM
    # ------------------------------------------------------------------ #
    DEPLOY_ENV: str = os.getenv("DEPLOY_ENV", "local")
    APP_NAME: str = os.getenv("APP_NAME", "utility-lead-platform")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ------------------------------------------------------------------ #
    # PLATFORM / BRAND
    # ------------------------------------------------------------------ #
    TB_BRAND_NAME: str = os.getenv("TB_BRAND_NAME", "Troy & Banks")
    TB_OFFICE_LOCATION: str = os.getenv("TB_OFFICE_LOCATION", "Buffalo, NY")
    UNSUBSCRIBE_INSTRUCTION: str = os.getenv(
        "UNSUBSCRIBE_INSTRUCTION",
        "To unsubscribe reply with STOP.",
    )

    # ------------------------------------------------------------------ #
    # LLM
    # ------------------------------------------------------------------ #
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ------------------------------------------------------------------ #
    # SEARCH
    # ------------------------------------------------------------------ #
    SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "tavily")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")

    # ------------------------------------------------------------------ #
    # SCRAPING
    # ------------------------------------------------------------------ #
    PROXY_PROVIDER: str = os.getenv("PROXY_PROVIDER", "scraperapi")
    SCRAPERAPI_KEY: str = os.getenv("SCRAPERAPI_KEY", "")
    BRIGHTDATA_KEY: str = os.getenv("BRIGHTDATA_KEY", "")
    REQUEST_DELAY_SECONDS: int = int(os.getenv("REQUEST_DELAY_SECONDS", "2"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    SCRAPER_REQUEST_TIMEOUT_SECONDS: int = int(
        os.getenv("SCRAPER_REQUEST_TIMEOUT_SECONDS", "30")
    )
    SCRAPER_USER_AGENT: str = os.getenv(
        "SCRAPER_USER_AGENT",
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    )

    # ------------------------------------------------------------------ #
    # CONTACT ENRICHMENT
    # ------------------------------------------------------------------ #
    ENRICHMENT_PROVIDER: str = os.getenv("ENRICHMENT_PROVIDER", "hunter")
    HUNTER_API_KEY: str = os.getenv("HUNTER_API_KEY", "")
    APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")

    # ------------------------------------------------------------------ #
    # DATABASE
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://admin:password@localhost:5432/leads",
    )

    # ------------------------------------------------------------------ #
    # EMAIL
    # ------------------------------------------------------------------ #
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "sendgrid")
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    SENDGRID_FROM_EMAIL: str = os.getenv("SENDGRID_FROM_EMAIL", "")
    INSTANTLY_API_KEY: str = os.getenv("INSTANTLY_API_KEY", "")
    INSTANTLY_CAMPAIGN_ID: str = os.getenv("INSTANTLY_CAMPAIGN_ID", "")
    INSTANTLY_API_BASE_URL: str = os.getenv(
        "INSTANTLY_API_BASE_URL",
        "https://api.instantly.ai",
    )
    INSTANTLY_REQUEST_TIMEOUT_SECONDS: int = int(
        os.getenv("INSTANTLY_REQUEST_TIMEOUT_SECONDS", "30")
    )
    EMAIL_DAILY_LIMIT: int = int(os.getenv("EMAIL_DAILY_LIMIT", "50"))
    FOLLOWUP_DAY_1: int = int(os.getenv("FOLLOWUP_DAY_1", "3"))
    FOLLOWUP_DAY_2: int = int(os.getenv("FOLLOWUP_DAY_2", "7"))
    FOLLOWUP_DAY_3: int = int(os.getenv("FOLLOWUP_DAY_3", "14"))

    # ------------------------------------------------------------------ #
    # SCOUT SCHEDULING
    # ------------------------------------------------------------------ #
    SCOUT_TARGET_INDUSTRIES: str = os.getenv("SCOUT_TARGET_INDUSTRIES", "all")
    SCOUT_TARGET_LOCATIONS: str = os.getenv("SCOUT_TARGET_LOCATIONS", "all")
    SCOUT_WEEKLY_TARGET_COUNT: int = int(
        os.getenv("SCOUT_WEEKLY_TARGET_COUNT", "20")
    )

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    API_KEY: str = os.getenv("API_KEY", "")

    # ------------------------------------------------------------------ #
    # ALERTS
    # ------------------------------------------------------------------ #
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    ALERT_EMAIL: str = os.getenv("ALERT_EMAIL", "")

    # ------------------------------------------------------------------ #
    # SCORING WEIGHTS
    # ------------------------------------------------------------------ #
    SCORE_WEIGHT_RECOVERY: float = float(os.getenv("SCORE_WEIGHT_RECOVERY", "0.40"))
    SCORE_WEIGHT_INDUSTRY: float = float(os.getenv("SCORE_WEIGHT_INDUSTRY", "0.25"))
    SCORE_WEIGHT_MULTISITE: float = float(os.getenv("SCORE_WEIGHT_MULTISITE", "0.20"))
    SCORE_WEIGHT_DATA_QUALITY: float = float(os.getenv("SCORE_WEIGHT_DATA_QUALITY", "0.15"))
    HIGH_SCORE_THRESHOLD: int = int(os.getenv("HIGH_SCORE_THRESHOLD", "70"))
    MEDIUM_SCORE_THRESHOLD: int = int(os.getenv("MEDIUM_SCORE_THRESHOLD", "40"))

    # ------------------------------------------------------------------ #
    # TROY & BANKS
    # ------------------------------------------------------------------ #
    TB_CONTINGENCY_FEE: float = float(os.getenv("TB_CONTINGENCY_FEE", "0.24"))
    TB_SENDER_NAME: str = os.getenv("TB_SENDER_NAME", "")
    TB_SENDER_TITLE: str = os.getenv("TB_SENDER_TITLE", "")
    TB_PHONE: str = os.getenv("TB_PHONE", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()


#Usage from any agent:
# from config.settings import get_settings
# settings = get_settings()
# print(settings.LLM_PROVIDER)