from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    betaseries_api_key: str
    betaseries_client_secret: str
    betaseries_access_token: str
    betaseries_user_id: str
    ollama_model: str
    ollama_base_url: str
    ollama_num_ctx: int
    ollama_num_predict: int
    ollama_timeout: float
    db_path: Path
    rpa_user_data_dir: Path
    platform_config_path: Path
    rpa_browser_extension_path: Path | None
    rpa_cdp_url: str
    admin_token: str
    crunchyroll_email: str
    crunchyroll_password: str
    crunchyroll_authorization: str
    crunchyroll_profile_id: str
    crunchyroll_locale: str

    @classmethod
    def from_env(cls) -> "Settings":
        extension_path = os.getenv("RPA_BROWSER_EXTENSION_PATH", "").strip()
        return cls(
            betaseries_api_key=os.getenv("BETASERIES_API_KEY", ""),
            betaseries_client_secret=os.getenv(
                "BETASERIES_CLIENT_SECRET",
                os.getenv("BETASERIES_OAUTH2_KEY", ""),
            ),
            betaseries_access_token=os.getenv("BETASERIES_ACCESS_TOKEN", ""),
            betaseries_user_id=os.getenv("BETASERIES_USER_ID", ""),
            ollama_model=os.getenv("OLLAMA_MODEL", "gemma3:4b"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
            ollama_num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "4096")),
            ollama_timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")),
            db_path=Path(os.getenv("STREAMING_DB_PATH", "streaming.db")),
            rpa_user_data_dir=Path(
                os.getenv("RPA_USER_DATA_DIR", ".playwright-profile")
            ),
            platform_config_path=Path(
                os.getenv("PLATFORM_CONFIG_PATH", "config/platforms.example.json")
            ),
            rpa_browser_extension_path=Path(extension_path) if extension_path else None,
            rpa_cdp_url=os.getenv("RPA_CDP_URL", "").strip(),
            admin_token=os.getenv("ADMIN_TOKEN", "").strip(),
            crunchyroll_email=os.getenv("CRUNCHYROLL_EMAIL", ""),
            crunchyroll_password=os.getenv("CRUNCHYROLL_PASSWORD", ""),
            crunchyroll_authorization=os.getenv("CRUNCHYROLL_AUTHORIZATION", ""),
            crunchyroll_profile_id=os.getenv("CRUNCHYROLL_PROFILE_ID", ""),
            crunchyroll_locale=os.getenv("CRUNCHYROLL_LOCALE", "fr-FR"),
        )
