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
        betaseries = _load_betaseries_config()
        ollama = _load_ollama_config()
        crunchyroll = _load_crunchyroll_config()
        profiles = _load_profiles_from_env()
        default_profile_key = _load_default_profile_key(profiles)
        platform_config = _load_streaming_platform_config()
        streaming_platforms = _load_streaming_platforms(platform_config)
        credentials = _credentials_from_platform_config(platform_config)
        profile_names = _profile_names_from_platform_config(platform_config)
        return cls(
            betaseries_api_key=betaseries["api_key"],
            betaseries_client_secret=betaseries["client_secret"],
            betaseries_access_token=betaseries["access_token"],
            betaseries_user_id=betaseries["user_id"],
            ollama_model=ollama["model"],
            ollama_base_url=ollama["base_url"],
            ollama_num_ctx=int(ollama["num_ctx"]),
            ollama_num_predict=int(ollama["num_predict"]),
            ollama_timeout=float(ollama["timeout"]),
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
            crunchyroll_email=crunchyroll["email"],
            crunchyroll_password=crunchyroll["password"],
            crunchyroll_authorization=crunchyroll["authorization"],
            crunchyroll_profile_id=crunchyroll["profile_id"],
            crunchyroll_locale=crunchyroll["locale"],
            rpa_credentials=credentials,
            rpa_profile_names=profile_names,
            streaming_platforms=streaming_platforms,
            profiles=profiles,
            default_profile_key=default_profile_key,
        )


def _load_betaseries_config() -> dict[str, str]:
    fallback = {
        "api_key": os.getenv("BETASERIES_API_KEY", ""),
        "client_secret": os.getenv(
            "BETASERIES_CLIENT_SECRET",
            os.getenv("BETASERIES_OAUTH2_KEY", ""),
        ),
        "access_token": os.getenv("BETASERIES_ACCESS_TOKEN", ""),
        "user_id": os.getenv("BETASERIES_USER_ID", ""),
    }
    return _load_named_config(
        os.getenv("BETASERIES_CONFIG_FILE", "").strip(),
        "BETASERIES_CONFIG_FILE",
        fallback,
    )


def _load_ollama_config() -> dict[str, str]:
    fallback = {
        "model": os.getenv("OLLAMA_MODEL", "gemma3:4b"),
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "num_ctx": os.getenv("OLLAMA_NUM_CTX", "32768"),
        "num_predict": os.getenv("OLLAMA_NUM_PREDICT", "4096"),
        "timeout": os.getenv("OLLAMA_TIMEOUT", "300"),
    }
    return _load_named_config(
        os.getenv("OLLAMA_CONFIG_FILE", "").strip(),
        "OLLAMA_CONFIG_FILE",
        fallback,
    )


def _load_crunchyroll_config() -> dict[str, str]:
    fallback = {
        "email": os.getenv("CRUNCHYROLL_EMAIL", ""),
        "password": os.getenv("CRUNCHYROLL_PASSWORD", ""),
        "authorization": os.getenv("CRUNCHYROLL_AUTHORIZATION", ""),
        "profile_id": os.getenv("CRUNCHYROLL_PROFILE_ID", ""),
        "locale": os.getenv("CRUNCHYROLL_LOCALE", "fr-FR"),
    }
    return _load_named_config(
        os.getenv("CRUNCHYROLL_CONFIG_FILE", "").strip(),
        "CRUNCHYROLL_CONFIG_FILE",
        fallback,
    )


def _load_named_config(
    raw_path: str,
    variable_name: str,
    fallback: dict[str, str],
) -> dict[str, str]:
    loaded = _load_json_file_object(raw_path, variable_name)
    if loaded is None:
        return fallback
    values = dict(fallback)
    for key, value in loaded.items():
        values[str(key)] = "" if value is None else str(value)
    return values


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
    file_config = _load_json_file_object(
        os.getenv("STREAMING_PLATFORM_CONFIG_FILE", "").strip(),
        "STREAMING_PLATFORM_CONFIG_FILE",
    )
    if file_config is not None:
        return _normalize_platform_config(file_config, legacy_config)

    raw_config = os.getenv("STREAMING_PLATFORM_CONFIG", "").strip()
    if not raw_config:
        return legacy_config
    parsed = _load_json_object(raw_config, "STREAMING_PLATFORM_CONFIG")
    return _normalize_platform_config(parsed, legacy_config)


def _normalize_platform_config(
    parsed: dict[str, object],
    fallback: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
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
    for platform, values in fallback.items():
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
    file_mapping = _load_json_file_object(
        os.getenv("STREAMING_PLATFORMS_FILE", "").strip(),
        "STREAMING_PLATFORMS_FILE",
    )
    if file_mapping is not None:
        return {
            str(platform): bool(enabled)
            for platform, enabled in file_mapping.items()
        }

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


def _load_json_file_object(
    raw_path: str, variable_name: str
) -> dict[str, object] | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        raw_value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{variable_name} points to an unreadable file: {path}") from exc
    return _load_json_object(raw_value, variable_name)


def _load_profiles_from_env() -> dict[str, StreamingProfile]:
    file_profiles = _load_json_file_object(
        os.getenv("STREAMING_PROFILES_FILE", "").strip(),
        "STREAMING_PROFILES_FILE",
    )
    if file_profiles is not None:
        profiles = _parse_profiles_json(file_profiles)
        if profiles:
            return profiles

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


def _parse_profiles_json(raw_profiles: dict[str, object]) -> dict[str, StreamingProfile]:
    profiles_payload = raw_profiles.get("profiles")
    if isinstance(profiles_payload, dict):
        raw_profiles = profiles_payload

    profiles: dict[str, StreamingProfile] = {}
    for key, raw_profile in raw_profiles.items():
        if not isinstance(raw_profile, dict):
            continue
        profile_key = str(raw_profile.get("key") or key)
        profiles[profile_key] = StreamingProfile(
            key=profile_key,
            label=str(raw_profile.get("label") or profile_key),
            technical_id=str(
                raw_profile.get("technical_id")
                or raw_profile.get("id")
                or profile_key
            ),
            is_junior=_parse_bool(str(raw_profile.get("is_junior") or "")),
        )
    return profiles


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
    profiles_config = _load_json_file_object(
        os.getenv("STREAMING_PROFILES_FILE", "").strip(),
        "STREAMING_PROFILES_FILE",
    )
    if profiles_config is not None:
        requested = str(profiles_config.get("default_profile_key") or "").strip()
        if requested and requested in profiles:
            return requested

    requested_config = _load_json_file_object(
        os.getenv("STREAMING_PROFILE_DEFAULTS_FILE", "").strip(),
        "STREAMING_PROFILE_DEFAULTS_FILE",
    )
    if requested_config is not None:
        requested = str(requested_config.get("default_profile_key") or "").strip()
        if requested and requested in profiles:
            return requested

    requested = os.getenv("DEFAULT_PROFILE_KEY", "").strip()
    if requested and requested in profiles:
        return requested
    return next(iter(profiles))


def _env_bool(name: str) -> bool:
    return _parse_bool(os.getenv(name, ""))


def _parse_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y", "on", "junior"}
