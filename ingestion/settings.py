from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class StreamingProfile:
    key: str
    label: str
    technical_id: str
    is_junior: bool = False


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
    rpa_cdp_timeout_ms: int
    admin_token: str
    crunchyroll_email: str
    crunchyroll_password: str
    crunchyroll_authorization: str
    crunchyroll_profile_id: str
    crunchyroll_locale: str
    rpa_credentials: dict[str, dict[str, str]]
    rpa_profile_names: dict[str, str]
    streaming_platforms: dict[str, bool]
    profiles: dict[str, StreamingProfile]
    default_profile_key: str

    @classmethod
    def from_env(cls) -> "Settings":
        extension_path = os.getenv("RPA_BROWSER_EXTENSION_PATH", "").strip()
        profiles = _load_profiles_from_env()
        default_profile_key = _load_default_profile_key(profiles)
        platform_config = _load_streaming_platform_config()
        streaming_platforms = _load_streaming_platforms(platform_config)
        credentials = _credentials_from_platform_config(platform_config)
        profile_names = _profile_names_from_platform_config(platform_config)
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
            rpa_cdp_timeout_ms=int(os.getenv("RPA_CDP_TIMEOUT_MS", "30000")),
            admin_token=os.getenv("ADMIN_TOKEN", "").strip(),
            crunchyroll_email=os.getenv("CRUNCHYROLL_EMAIL", ""),
            crunchyroll_password=os.getenv("CRUNCHYROLL_PASSWORD", ""),
            crunchyroll_authorization=os.getenv("CRUNCHYROLL_AUTHORIZATION", ""),
            crunchyroll_profile_id=os.getenv("CRUNCHYROLL_PROFILE_ID", ""),
            crunchyroll_locale=os.getenv("CRUNCHYROLL_LOCALE", "fr-FR"),
            rpa_credentials=credentials,
            rpa_profile_names=profile_names,
            streaming_platforms=streaming_platforms,
            profiles=profiles,
            default_profile_key=default_profile_key,
        )


PLATFORM_ENV_PREFIXES = {
    "crunchyroll": "CRUNCHYROLL",
    "netflix": "NETFLIX",
    "prime_video": "PRIME_VIDEO",
    "disney_plus": "DISNEY_PLUS",
    "canal_plus": "CANAL_PLUS",
    "apple_tv_plus": "APPLE_TV",
    "max": "MAX",
    "paramount_plus": "PARAMOUNT_PLUS",
    "ocs": "OCS",
}


def _load_streaming_platform_config() -> dict[str, dict[str, str]]:
    legacy_config = _legacy_platform_config_from_env()
    raw_config = os.getenv("STREAMING_PLATFORM_CONFIG", "").strip()
    if not raw_config:
        return legacy_config
    parsed = _load_json_object(raw_config, "STREAMING_PLATFORM_CONFIG")
    config: dict[str, dict[str, str]] = {}
    for platform, values in parsed.items():
        if not isinstance(values, dict):
            continue
        config[str(platform)] = {
            "email": str(values.get("email") or ""),
            "password": str(values.get("password") or ""),
            "profile_name": str(
                values.get("profile_name")
                or values.get("profil_name")
                or values.get("profile")
                or ""
            ),
        }
    for platform, values in legacy_config.items():
        config.setdefault(platform, values)
    return config


def _legacy_platform_config_from_env() -> dict[str, dict[str, str]]:
    config: dict[str, dict[str, str]] = {}
    for platform, prefix in PLATFORM_ENV_PREFIXES.items():
        config[platform] = {
            "email": os.getenv(f"{prefix}_EMAIL", ""),
            "password": os.getenv(f"{prefix}_PASSWORD", ""),
            "profile_name": os.getenv(f"{prefix}_PROFILE_NAME", ""),
        }
    return config


def _load_streaming_platforms(
    platform_config: dict[str, dict[str, str]]
) -> dict[str, bool]:
    raw_mapping = os.getenv("STREAMING_PLATFORMS", "").strip()
    if raw_mapping:
        parsed = _load_json_object(raw_mapping, "STREAMING_PLATFORMS")
        return {str(platform): bool(enabled) for platform, enabled in parsed.items()}
    return {platform: True for platform in platform_config}


def _credentials_from_platform_config(
    platform_config: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    return {
        platform: {
            "email": values.get("email", ""),
            "password": values.get("password", ""),
        }
        for platform, values in platform_config.items()
    }


def _profile_names_from_platform_config(
    platform_config: dict[str, dict[str, str]]
) -> dict[str, str]:
    return {
        platform: values.get("profile_name", "")
        for platform, values in platform_config.items()
    }


def _load_json_object(raw_value: str, variable_name: str) -> dict[str, object]:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{variable_name} must contain a valid JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{variable_name} must contain a JSON object")
    return value


def _load_profiles_from_env() -> dict[str, StreamingProfile]:
    raw_profiles = os.getenv("STREAMING_PROFILES", "").strip()
    if raw_profiles:
        profiles = _parse_profile_matrix(raw_profiles)
        if profiles:
            return profiles

    fallback_key = os.getenv("DEFAULT_PROFILE_KEY", "default").strip() or "default"
    fallback_label = os.getenv("DEFAULT_PROFILE_LABEL", "Profil par défaut").strip()
    return {
        fallback_key: StreamingProfile(
            key=fallback_key,
            label=fallback_label or fallback_key,
            technical_id=os.getenv("DEFAULT_PROFILE_TECHNICAL_ID", fallback_key).strip()
            or fallback_key,
            is_junior=_env_bool("DEFAULT_PROFILE_IS_JUNIOR"),
        )
    }


def _parse_profile_matrix(raw_profiles: str) -> dict[str, StreamingProfile]:
    profiles: dict[str, StreamingProfile] = {}
    for chunk in raw_profiles.split(";"):
        parts = [part.strip() for part in chunk.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        key = parts[0]
        label = parts[1] or key
        technical_id = parts[2] if len(parts) >= 3 and parts[2] else key
        is_junior = _parse_bool(parts[3]) if len(parts) >= 4 else False
        profiles[key] = StreamingProfile(
            key=key,
            label=label,
            technical_id=technical_id,
            is_junior=is_junior,
        )
    return profiles


def _load_default_profile_key(profiles: dict[str, StreamingProfile]) -> str:
    requested = os.getenv("DEFAULT_PROFILE_KEY", "").strip()
    if requested and requested in profiles:
        return requested
    return next(iter(profiles))


def _env_bool(name: str) -> bool:
    return _parse_bool(os.getenv(name, ""))


def _parse_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y", "on", "junior"}
