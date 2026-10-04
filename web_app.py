from __future__ import annotations

import calendar as month_calendar
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from ingestion.db import StreamingDB
from ingestion.runtime_platform import portable_file_lock
from ingestion.settings import Settings

PLATFORM_LABELS = {
    "unknown": "BetaSeries",
    "canal_plus": "CANAL+",
    "crunchyroll": "Crunchyroll",
    "disney_plus": "Disney+",
    "netflix": "Netflix",
    "prime_video": "Prime Video",
}
VALID_SERIES_TITLE_SQL = (
    "NOT (s.titre LIKE '__/__/%' OR s.titre LIKE '%Report a problem%') "
    "AND COALESCE(LOWER(s.imdb_kind), '') NOT IN ('movie', 'film')"
)
VALID_HISTORY_DATE_SQL = (
    "CASE WHEN h.date_vu GLOB '????-??-??*' "
    "AND DATE(h.date_vu) <= DATE('now') THEN DATE(h.date_vu) END"
)

PLATFORM_MARKS = {
    "canal_plus": "C+",
    "crunchyroll": "CR",
    "disney_plus": "D+",
    "netflix": "N",
    "prime_video": "PV",
    "unknown": "BS",
}

SUPPORTED_LANGUAGES = {
    "fr": {"flag": "🇫🇷", "label": "Français"},
    "en": {"flag": "🇬🇧", "label": "English"},
    "es": {"flag": "🇪🇸", "label": "Español"},
}

TRANSLATIONS = {
    "fr": {
        "admin": "Admin",
        "all_genres": "Tous les genres",
        "all_platforms": "Toutes les plateformes",
        "all": "Tous",
        "calendar": "Calendrier",
        "calendar_empty": "Aucune sortie connue pour ce mois et ces filtres.",
        "calendar_episodes": "Épisodes",
        "calendar_series": "Séries",
        "calendar_title": "Séries par calendrier",
        "current_month": "Ce mois-ci",
        "dated_history_none": "Aucun visionnage daté",
        "episodes_seen": "épisodes vus",
        "go": "GO",
        "histories": "Historiques",
        "language": "Langue",
        "movies": "Films",
        "movies_empty": "Aucun film ne correspond à cette recherche.",
        "movies_intro": "Vue locale issue des historiques de streaming, enrichie avec BetaSeries et IMDb.",
        "movies_title": "Films par plateformes",
        "next": "Prochain",
        "no_known_release": "Aucune sortie connue",
        "page": "Page",
        "page_size": "Par page",
        "platforms": "Plateformes",
        "previous": "Précédent",
        "search": "Rechercher",
        "search_movie": "Rechercher un film",
        "search_series": "Rechercher une série",
        "select_month": "Sélection mois",
        "series": "Séries",
        "series_empty": "Aucune série ne correspond à cette recherche.",
        "series_intro": "Vue locale issue de SQLite, avec historique et calendrier BetaSeries.",
        "series_title": "Séries par plateformes",
        "synced": "Synchros BetaSeries",
        "today": "Aujourd'hui",
        "unwatched": "Non vus",
        "watched": "Vus",
    },
    "en": {
        "admin": "Admin",
        "all_genres": "All genres",
        "all_platforms": "All platforms",
        "all": "All",
        "calendar": "Calendar",
        "calendar_empty": "No known releases for this month and filters.",
        "calendar_episodes": "Episodes",
        "calendar_series": "Series",
        "calendar_title": "Series calendar",
        "current_month": "This month",
        "dated_history_none": "No dated viewing",
        "episodes_seen": "episodes watched",
        "go": "GO",
        "histories": "History",
        "language": "Language",
        "movies": "Movies",
        "movies_empty": "No movie matches this search.",
        "movies_intro": "Local view built from streaming histories, enriched with BetaSeries and IMDb.",
        "movies_title": "Movies by platform",
        "next": "Next",
        "no_known_release": "No known release",
        "page": "Page",
        "page_size": "Per page",
        "platforms": "Platforms",
        "previous": "Previous",
        "search": "Search",
        "search_movie": "Search a movie",
        "search_series": "Search a series",
        "select_month": "Select month",
        "series": "Series",
        "series_empty": "No series matches this search.",
        "series_intro": "Local SQLite view with viewing history and BetaSeries calendar.",
        "series_title": "Series by platform",
        "synced": "BetaSeries syncs",
        "today": "Today",
        "unwatched": "Unwatched",
        "watched": "Watched",
    },
    "es": {
        "admin": "Admin",
        "all_genres": "Todos los géneros",
        "all_platforms": "Todas las plataformas",
        "all": "Todo",
        "calendar": "Calendario",
        "calendar_empty": "No hay estrenos conocidos para este mes y estos filtros.",
        "calendar_episodes": "Episodios",
        "calendar_series": "Series",
        "calendar_title": "Series por calendario",
        "current_month": "Este mes",
        "dated_history_none": "Sin visionado fechado",
        "episodes_seen": "episodios vistos",
        "go": "GO",
        "histories": "Historiales",
        "language": "Idioma",
        "movies": "Películas",
        "movies_empty": "Ninguna película coincide con esta búsqueda.",
        "movies_intro": "Vista local basada en historiales de streaming, enriquecida con BetaSeries e IMDb.",
        "movies_title": "Películas por plataforma",
        "next": "Próximo",
        "no_known_release": "Sin estreno conocido",
        "page": "Página",
        "page_size": "Por página",
        "platforms": "Plataformas",
        "previous": "Anterior",
        "search": "Buscar",
        "search_movie": "Buscar una película",
        "search_series": "Buscar una serie",
        "select_month": "Seleccionar mes",
        "series": "Series",
        "series_empty": "Ninguna serie coincide con esta búsqueda.",
        "series_intro": "Vista local desde SQLite, con historial y calendario BetaSeries.",
        "series_title": "Series por plataforma",
        "synced": "Sincronizaciones BetaSeries",
        "today": "Hoy",
        "unwatched": "No vistos",
        "watched": "Vistos",
    },
}


def create_app() -> Flask:
    app = Flask(__name__)
    settings = Settings.from_env()
    app.config["DB_PATH"] = settings.db_path
    app.config["ADMIN_TOKEN"] = settings.admin_token
    app.config["STREAMING_PROFILES"] = settings.profiles
    app.config["DEFAULT_PROFILE_KEY"] = settings.default_profile_key
    app.config["STREAMING_PLATFORM_PROFILES"] = settings.rpa_platform_profiles
    app.config["STREAMING_PLATFORMS"] = settings.streaming_platforms
    StreamingDB(settings.db_path).init_schema()

    @app.teardown_appcontext
    def close_db(_error: BaseException | None = None) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def protect_admin_routes():
        g.lang = resolve_language()
        if not request.path.startswith("/admin"):
            return None
        admin_token = current_app.config["ADMIN_TOKEN"]
        credentials = request.authorization
        valid_credentials = bool(
            admin_token
            and credentials
            and hmac.compare_digest(credentials.username, "admin")
            and hmac.compare_digest(credentials.password or "", admin_token)
        )
        if valid_credentials:
            return None
        return (
            "Administration disabled or authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Streaming DB admin"'},
        )

    @app.after_request
    def apply_response_policy(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        if request.args.get("lang") in SUPPORTED_LANGUAGES:
            response.set_cookie(
                "streaming_lang",
                request.args["lang"],
                max_age=60 * 60 * 24 * 365,
                secure=request.is_secure,
                httponly=True,
                samesite="Lax",
            )
        if request.args.get("profile") in current_app.config.get(
            "STREAMING_PROFILES", {}
        ):
            response.set_cookie(
                "streaming_profile",
                request.args["profile"],
                max_age=60 * 60 * 24 * 365,
                secure=request.is_secure,
                httponly=True,
                samesite="Lax",
            )
        return response

    @app.context_processor
    def inject_i18n_helpers():
        return {
            "current_lang": g.get("lang", "fr"),
            "language_options": SUPPORTED_LANGUAGES,
            "language_url": language_url,
            "t": translate,
        }

    @app.get("/")
    def index():
        query = request.args.get("q", "").strip()
        selected_platform = request.args.get("platform", "").strip()
        selected_genre = request.args.get("genre", "").strip()
        active_profile = resolve_profile()
        try:
            page = max(1, int(request.args.get("page", 1)))
            per_page = int(request.args.get("per_page", 10))
        except ValueError:
            abort(400, description="Paramètre de pagination invalide.")
        if per_page not in {10, 20, 50}:
            abort(400, description="Le nombre d'éléments doit être 10, 20 ou 50.")
        platforms = fetch_platforms()
        genres = fetch_genres()
        series = search_series(
            query=query,
            platform=selected_platform,
            genre=selected_genre,
            profile_key=active_profile["key"],
            junior_only=active_profile["is_junior"],
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_series = count_series(
            query,
            selected_platform,
            selected_genre,
            profile_key=active_profile["key"],
            junior_only=active_profile["is_junior"],
        )
        stats = fetch_stats()
        return render_template(
            "index.html",
            query=query,
            selected_platform=selected_platform,
            selected_genre=selected_genre,
            platforms=platforms,
            genres=genres,
            platform_labels=PLATFORM_LABELS,
            platform_marks=PLATFORM_MARKS,
            series=series,
            stats=stats,
            page=page,
            per_page=per_page,
            total_series=total_series,
            total_pages=max(1, (total_series + per_page - 1) // per_page),
            active_profile=active_profile,
            profile_options=profile_options(),
        )

    @app.get("/movies")
    def movies_view():
        query = request.args.get("q", "").strip()
        selected_platform = request.args.get("platform", "").strip()
        selected_genre = request.args.get("genre", "").strip()
        active_profile = resolve_profile()
        try:
            page = max(1, int(request.args.get("page", 1)))
            per_page = int(request.args.get("per_page", 10))
        except ValueError:
            abort(400, description="Paramètre de pagination invalide.")
        if per_page not in {10, 20, 50}:
            abort(400, description="Le nombre d'éléments doit être 10, 20 ou 50.")
        platforms = fetch_movie_platforms()
        genres = fetch_genres(content_type="movie")
        movies = fetch_movies(
            query=query,
            platform=selected_platform,
            genre=selected_genre,
            profile_key=active_profile["key"],
            junior_only=active_profile["is_junior"],
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_movies = count_movies(
            query,
            selected_platform,
            selected_genre,
            profile_key=active_profile["key"],
            junior_only=active_profile["is_junior"],
        )
        return render_template(
            "movies.html",
            movies=movies,
            query=query,
            selected_platform=selected_platform,
            selected_genre=selected_genre,
            platforms=platforms,
            genres=genres,
            platform_labels=PLATFORM_LABELS,
            platform_marks=PLATFORM_MARKS,
            stats=fetch_movie_stats(),
            page=page,
            per_page=per_page,
            total_movies=total_movies,
            total_pages=max(1, (total_movies + per_page - 1) // per_page),
            active_profile=active_profile,
            profile_options=profile_options(),
        )

    @app.get("/series/<int:series_id>")
    def series_detail(series_id: int):
        active_profile = resolve_profile()
        serie = fetch_series(series_id)
        if serie is None:
            abort(404)
        upcoming = fetch_calendar(series_id, only_upcoming=True)
        full_calendar = fetch_calendar(series_id, only_upcoming=False)
        history = fetch_history(series_id)
        serie["watched_episode_count"] = count_watched_episodes(history)
        if has_complete_season_marker(history):
            serie["watched_episode_count"] = (
                serie.get("episodes_count") or serie["watched_episode_count"]
            )
        serie["genres_list"] = parse_genres(serie.get("genres"))
        related_series = fetch_related_series(series_id, serie["genres_list"])
        profile_progress = fetch_profile_progress(series_id)
        status = infer_status(serie, upcoming, full_calendar)
        return render_template(
            "series_detail.html",
            serie=serie,
            platform_labels=PLATFORM_LABELS,
            upcoming=upcoming,
            full_calendar=full_calendar,
            history=history[:50],
            status=status,
            platform_marks=PLATFORM_MARKS,
            related_series=related_series,
            active_profile=active_profile,
            profile_progress=profile_progress,
        )

    @app.get("/admin")
    def admin_view():
        return redirect(url_for("admin_delete_view"))

    @app.get("/admin/delete")
    def admin_delete_view():
        query = request.args.get("q", "").strip()
        movie_query = request.args.get("movie_q", "").strip()
        return render_template(
            "admin_delete.html",
            series=fetch_admin_series(query),
            movies=fetch_admin_movies(movie_query),
            query=query,
            movie_query=movie_query,
            platform_labels=PLATFORM_LABELS,
        )

    @app.get("/admin/rpa")
    def admin_rpa_view():
        return render_template(
            "admin_rpa.html",
            platforms=fetch_admin_platforms(),
            rpa_state=fetch_admin_rpa_state(),
            platform_labels=PLATFORM_LABELS,
        )

    @app.get("/admin/rpa/state")
    def admin_rpa_state_api():
        return jsonify(fetch_admin_rpa_state())

    @app.get("/admin/logs")
    def admin_logs_view():
        return render_template(
            "admin_logs.html",
            ingestion_logs=fetch_recent_ingestion_logs(),
        )

    @app.get("/admin/kpis")
    def admin_kpis_view():
        selected_platform = request.args.get("platform", "").strip()
        return render_template(
            "admin_kpis.html",
            kpis=fetch_admin_kpis(selected_platform or None),
            selected_platform=selected_platform,
            platform_labels=PLATFORM_LABELS,
        )

    @app.get("/admin/profiles")
    def admin_profiles_view():
        return render_template(
            "admin_profiles.html",
            platform_profiles=platform_profile_options(),
            meta_profiles=read_meta_profiles(),
            platforms=fetch_admin_platforms(),
            has_meta_profiles=has_meta_profiles(),
            platform_labels=PLATFORM_LABELS,
        )

    @app.get("/admin/alerts")
    def admin_alerts_view():
        return render_template(
            "admin_alerts.html",
            mobile_settings=read_mobile_settings(),
        )

    @app.post("/admin/profiles/meta")
    def admin_create_meta_profile():
        label = request.form.get("label", "").strip()
        profile_key = slugify(request.form.get("key", "") or label)
        if not label or not profile_key:
            abort(400, description="Profil invalide.")
        mapping = {
            key.removeprefix("platform_"): value.strip()
            for key, value in request.form.items()
            if key.startswith("platform_") and value.strip()
        }
        known_platforms = {item["platform"] for item in fetch_admin_platforms()}
        mapping = {
            platform: profile_name
            for platform, profile_name in mapping.items()
            if platform in known_platforms
        }
        meta_profiles = read_meta_profiles()
        meta_profiles = [
            profile for profile in meta_profiles if profile.get("key") != profile_key
        ]
        meta_profiles.append({"key": profile_key, "label": label, "platforms": mapping})
        write_json_file(META_PROFILES_PATH, meta_profiles)
        return redirect(url_for("admin_profiles_view", saved="1"))

    @app.post("/admin/profiles/mobile-settings")
    def admin_update_mobile_settings():
        settings = read_mobile_settings()
        settings["sync_alert_hours"] = clamp_int(
            request.form.get("sync_alert_hours"), default=24, minimum=1, maximum=720
        )
        settings["sync_alert_enabled"] = request.form.get("sync_alert_enabled") == "1"
        settings["episode_alert_enabled"] = request.form.get("episode_alert_enabled") == "1"
        settings["hide_empty_calendar_days"] = request.form.get("hide_empty_calendar_days") == "1"
        settings["profile_progress_scope"] = (
            "platform"
            if request.form.get("profile_progress_scope") == "platform"
            else "meta"
        )
        write_json_file(MOBILE_SETTINGS_PATH, settings)
        return redirect(url_for("admin_alerts_view", saved="1"))

    @app.post("/admin/series/<int:series_id>/delete")
    def admin_delete_series(series_id: int):
        if request.form.get("confirmation") != "SUPPRIMER":
            abort(400, description="Confirmation invalide.")
        db_path = Path(current_app.config["DB_PATH"])
        backup = (
            db_path.parent
            / "backups"
            / f"streaming-before-delete-{datetime.now():%Y%m%d-%H%M%S}.db"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        counts = StreamingDB(db_path).delete_series(series_id)
        return redirect(
            url_for("admin_delete_view", deleted=counts["series"], backup=backup.name)
        )

    @app.post("/admin/movies/<int:movie_id>/delete")
    def admin_delete_movie(movie_id: int):
        if request.form.get("confirmation") != "SUPPRIMER":
            abort(400, description="Confirmation invalide.")
        db_path = Path(current_app.config["DB_PATH"])
        backup = backup_database(db_path, "movie-delete")
        counts = StreamingDB(db_path).delete_series(movie_id)
        return redirect(
            url_for(
                "admin_delete_view", deleted_movie=counts["series"], backup=backup.name
            )
        )

    @app.post("/admin/data/delete")
    def admin_delete_all_data():
        if request.form.get("confirmation") != "DELETE":
            abort(400, description="Confirmation invalide.")
        db_path = Path(current_app.config["DB_PATH"])
        backup = backup_database(db_path, "delete-all-data")
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for table_name in (
                "history",
                "calendar",
                "series_aliases",
                "series_sources",
                "raw_history",
                "raw_history_cards",
                "series",
            ):
                conn.execute(f"DELETE FROM {table_name}")
        return redirect(url_for("admin_delete_view", deleted_data=1, backup=backup.name))

    @app.post("/admin/rpa/<platform>/run")
    def admin_run_rpa(platform: str):
        known_platforms = {item["platform"] for item in fetch_admin_platforms()}
        if platform not in known_platforms:
            abort(404)
        active_profile = resolve_profile()
        job = enqueue_rpa_platform(
            platform, profile_key=active_profile["key"], source="web"
        )
        return redirect(
            url_for(
                "admin_rpa_view",
                rpa_started=platform,
                rpa_log=Path(job["log_path"]).name,
            )
        )

    @app.get("/calendar")
    def calendar_view():
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        raw_month = request.args.get("month", today.strftime("%Y-%m"))
        try:
            month = datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
            if not 1900 <= month.year <= 9998:
                raise ValueError("Month outside supported range")
        except ValueError:
            abort(400, description="Mois invalide (format AAAA-MM).")
        selected_platforms = list(dict.fromkeys(request.args.getlist("platform")))
        calendar_query = request.args.get("q", "").strip()
        calendar_genre = request.args.get("genre", "").strip()
        active_profile = resolve_profile()
        watched_filter = request.args.get("watched", "all")
        if watched_filter not in {"all", "watched", "unwatched"}:
            abort(400, description="Filtre de visionnage invalide.")
        options = fetch_calendar_platforms(month, calendar_query, calendar_genre)
        known_options = {item["platform"]: item for item in options}
        for item in fetch_platforms():
            known_options.setdefault(
                item["platform"],
                {"platform": item["platform"], "series_total": 0, "episode_total": 0},
            )
        options = sorted(known_options.values(), key=lambda item: item["platform"])
        episodes = fetch_upcoming_releases(
            month,
            today,
            selected_platforms,
            watched_filter=watched_filter,
            query=calendar_query,
            genre=calendar_genre,
            profile_key=active_profile["key"],
            junior_only=active_profile["is_junior"],
        )
        by_date: dict[str, list[dict]] = {}
        for episode in episodes:
            by_date.setdefault(episode["release_date"], []).append(episode)
        weeks = [
            [
                {"date": day, "episodes": by_date.get(day.isoformat(), [])}
                for day in week
            ]
            for week in month_calendar.Calendar(firstweekday=0).monthdatescalendar(
                month.year, month.month
            )
        ]
        previous = (
            date(month.year - 1, 12, 1)
            if month.month == 1
            else month.replace(month=month.month - 1)
        )
        following = (
            date(month.year + 1, 1, 1)
            if month.month == 12
            else month.replace(month=month.month + 1)
        )
        months = (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        )
        return render_template(
            "calendar.html",
            month=month,
            month_label=f"{months[month.month - 1].capitalize()} {month.year}",
            today=today,
            weeks=weeks,
            platforms=options,
            selected_platforms=selected_platforms,
            calendar_query=calendar_query,
            calendar_genre=calendar_genre,
            genres=fetch_genres(),
            watched_filter=watched_filter,
            platform_labels=PLATFORM_LABELS,
            episode_count=len(episodes),
            month_series_count=len({episode["serie_id"] for episode in episodes}),
            previous_month=previous.strftime("%Y-%m"),
            next_month=following.strftime("%Y-%m"),
            active_profile=active_profile,
            profile_options=profile_options(),
        )

    @app.get("/api/series/suggest")
    def series_suggestions():
        return jsonify(suggest_series(request.args.get("q", "")))

    @app.get("/api/movies/suggest")
    def movie_suggestions():
        return jsonify(suggest_movies(request.args.get("q", "")))

    @app.get("/api/mobile/bootstrap")
    def api_mobile_bootstrap():
        return jsonify(
            {
                "stats": {
                    "series": fetch_stats(),
                    "movies": fetch_movie_stats(),
                },
                "platforms": {
                    "series": fetch_platforms(),
                    "movies": fetch_movie_platforms(),
                },
                "genres": {
                    "series": fetch_genres(),
                    "movies": fetch_genres(content_type="movie"),
                },
                "platform_labels": PLATFORM_LABELS,
                "platform_marks": PLATFORM_MARKS,
                "profiles": profile_options(),
                "default_profile_key": current_app.config["DEFAULT_PROFILE_KEY"],
                "platform_profiles": platform_profile_options(),
                "meta_profiles": read_meta_profiles(),
                "has_meta_profiles": has_meta_profiles(),
                "mobile_settings": read_mobile_settings(),
                "rpa_platforms": fetch_admin_platforms(),
                "ingestion_statuses": fetch_mobile_ingestion_statuses(),
                "recent_ingestions": fetch_recent_ingestion_runs(limit_per_platform=5),
            }
        )

    @app.get("/api/mobile/settings")
    def api_mobile_settings():
        return jsonify(
            {
                "meta_profiles": read_meta_profiles(),
                "profiles": profile_options(),
                "mobile_settings": read_mobile_settings(),
                "platform_profiles": platform_profile_options(),
                "has_meta_profiles": has_meta_profiles(),
            }
        )

    @app.post("/api/mobile/settings")
    def api_mobile_update_settings():
        payload = request.get_json(silent=True) or {}
        settings = read_mobile_settings()
        settings["sync_alert_hours"] = clamp_int(
            payload.get("sync_alert_hours"),
            settings["sync_alert_hours"],
            1,
            720,
        )
        if "sync_alert_enabled" in payload:
            settings["sync_alert_enabled"] = bool(payload.get("sync_alert_enabled"))
        if "episode_alert_enabled" in payload:
            settings["episode_alert_enabled"] = bool(payload.get("episode_alert_enabled"))
        if "hide_empty_calendar_days" in payload:
            settings["hide_empty_calendar_days"] = bool(payload.get("hide_empty_calendar_days"))
        if payload.get("profile_progress_scope") in {"meta", "platform"}:
            settings["profile_progress_scope"] = payload.get("profile_progress_scope")
        write_json_file(MOBILE_SETTINGS_PATH, settings)
        return jsonify({"mobile_settings": settings})

    @app.post("/api/mobile/profiles/meta")
    def api_mobile_create_meta_profile():
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label") or "").strip()
        profile_key = slugify(str(payload.get("key") or label))
        mapping = payload.get("platforms")
        if not label or not profile_key or not isinstance(mapping, dict):
            abort(400, description="Méta-profil invalide.")
        known_platforms = {item["platform"] for item in fetch_admin_platforms()}
        cleaned_mapping = {
            str(platform): str(profile_name).strip()
            for platform, profile_name in mapping.items()
            if platform in known_platforms and str(profile_name).strip()
        }
        meta_profiles = [
            profile
            for profile in read_meta_profiles()
            if profile.get("key") != profile_key
        ]
        meta_profiles.append(
            {
                "key": profile_key,
                "label": label,
                "is_junior": bool(payload.get("is_junior", False)),
                "platforms": cleaned_mapping,
            }
        )
        write_json_file(META_PROFILES_PATH, meta_profiles)
        return jsonify({"meta_profiles": read_meta_profiles(), "profiles": profile_options()})

    @app.get("/api/mobile/rpa/platforms")
    def api_mobile_rpa_platforms():
        return jsonify({"platforms": fetch_admin_platforms()})

    @app.post("/api/mobile/rpa/<platform>/run")
    def api_mobile_run_rpa(platform: str):
        known_platforms = {item["platform"] for item in fetch_admin_platforms()}
        if platform not in known_platforms:
            abort(404)
        active_profile = resolve_profile()
        job = enqueue_rpa_platform(
            platform, profile_key=active_profile["key"], source="mobile"
        )
        return jsonify(
            {
                "status": "queued",
                "platform": platform,
                "profile": active_profile,
                "log": Path(job["log_path"]).name,
            }
        )

    @app.get("/api/mobile/titles")
    def api_mobile_titles():
        content_type = request.args.get("type", "series").strip().casefold()
        query = request.args.get("q", "").strip()
        platform = request.args.get("platform", "").strip()
        genre = request.args.get("genre", "").strip()
        active_profile = resolve_profile()
        include_all_profiles = request.args.get("profile") == "all"
        profile_key = None if include_all_profiles else active_profile["key"]
        junior_only = False if include_all_profiles else active_profile["is_junior"]
        page, per_page = parse_pagination_args(default_per_page=20, max_per_page=100)
        if content_type in {"movie", "movies", "film", "films"}:
            total = count_movies(
                query,
                platform,
                genre,
                profile_key=profile_key,
                junior_only=junior_only,
            )
            items = [
                mobile_title_summary(item, content_type="movie")
                for item in fetch_movies(
                    query=query,
                    platform=platform,
                    genre=genre,
                    profile_key=profile_key,
                    junior_only=junior_only,
                    limit=per_page,
                    offset=(page - 1) * per_page,
                )
            ]
            normalized_type = "movie"
        else:
            total = count_series(
                query,
                platform,
                genre,
                profile_key=profile_key,
                junior_only=junior_only,
            )
            items = [
                mobile_title_summary(item, content_type="series")
                for item in search_series(
                    query=query,
                    platform=platform,
                    genre=genre,
                    profile_key=profile_key,
                    junior_only=junior_only,
                    limit=per_page,
                    offset=(page - 1) * per_page,
                )
            ]
            normalized_type = "series"
        return jsonify(
            {
                "type": normalized_type,
                "items": items,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
                "profile": "all" if include_all_profiles else active_profile,
            }
        )

    @app.get("/api/mobile/titles/<int:title_id>")
    def api_mobile_title_detail(title_id: int):
        serie = fetch_series(title_id)
        if serie is None:
            abort(404)
        history = fetch_history(title_id)
        full_calendar = fetch_calendar(title_id, only_upcoming=False)
        upcoming = fetch_calendar(title_id, only_upcoming=True)
        serie["watched_episode_count"] = count_watched_episodes(history)
        if has_complete_season_marker(history):
            serie["watched_episode_count"] = (
                serie.get("episodes_count") or serie["watched_episode_count"]
            )
        serie["genres_list"] = parse_genres(serie.get("genres"))
        status = infer_status(serie, upcoming, full_calendar)
        return jsonify(
            mobile_title_detail(
                serie=serie,
                history=history[:50],
                calendar=full_calendar,
                upcoming=upcoming,
                status=status,
                profile_progress=fetch_profile_progress(
                    title_id,
                    scope=read_mobile_settings()["profile_progress_scope"],
                ),
            )
        )

    @app.get("/api/mobile/calendar")
    def api_mobile_calendar():
        selected_month = parse_month(request.args.get("month"))
        query = request.args.get("q", "").strip()
        genre = request.args.get("genre", "").strip()
        watched_filter = request.args.get("watched", "all")
        platforms = request.args.getlist("platform")
        active_profile = resolve_profile()
        include_all_profiles = request.args.get("profile") == "all"
        episodes = fetch_upcoming_releases(
            selected_month,
            date.today(),
            platforms,
            watched_filter=watched_filter,
            query=query,
            genre=genre,
            profile_key=None if include_all_profiles else active_profile["key"],
            junior_only=False if include_all_profiles else active_profile["is_junior"],
        )
        return jsonify(
            {
                "month": selected_month.strftime("%Y-%m"),
                "platforms": fetch_calendar_platforms(
                    selected_month, query=query, genre=genre
                ),
                "episodes": [mobile_calendar_episode(item) for item in episodes],
            }
        )

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DB_PATH"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def resolve_language() -> str:
    requested = request.args.get("lang") or request.cookies.get("streaming_lang")
    if requested in SUPPORTED_LANGUAGES:
        return requested
    accepted = request.accept_languages.best_match(SUPPORTED_LANGUAGES.keys())
    return accepted or "fr"


def translate(key: str) -> str:
    lang = g.get("lang", "fr")
    return TRANSLATIONS.get(lang, TRANSLATIONS["fr"]).get(
        key,
        TRANSLATIONS["fr"].get(key, key),
    )


def language_url(lang: str) -> str:
    args = request.args.to_dict(flat=False)
    args["lang"] = [lang]
    route_args = request.view_args or {}
    return url_for(request.endpoint or "index", **route_args, **args)


def profile_options() -> list[dict[str, Any]]:
    meta_profiles = read_meta_profiles()
    if meta_profiles:
        return [
            {
                "key": profile["key"],
                "label": profile["label"],
                "technical_id": profile["key"],
                "is_junior": bool(profile.get("is_junior", False)),
                "platforms": profile.get("platforms", {}),
            }
            for profile in meta_profiles
            if profile.get("key")
        ]
    profiles = current_app.config.get("STREAMING_PROFILES", {})
    return [
        {
            "key": profile.key,
            "label": profile.label,
            "technical_id": profile.technical_id,
            "is_junior": profile.is_junior,
        }
        for profile in profiles.values()
    ]


def has_meta_profiles() -> bool:
    return bool(read_meta_profiles())


def platform_profile_options() -> dict[str, list[dict[str, Any]]]:
    configured = current_app.config.get("STREAMING_PLATFORM_PROFILES", {})
    profiles = current_app.config.get("STREAMING_PROFILES", {})
    result: dict[str, list[dict[str, Any]]] = read_discovered_platform_profiles()
    for platform, mapping in configured.items():
        if platform in result and result[platform]:
            continue
        items = []
        for profile_key, platform_profile_name in mapping.items():
            profile = profiles.get(profile_key)
            items.append(
                {
                    "profile_key": profile_key,
                    "profile_label": profile.label if profile else profile_key,
                    "platform_profile_name": platform_profile_name,
                    "is_junior": profile.is_junior if profile else False,
                }
            )
        result[platform] = items
    return result


def read_discovered_platform_profiles() -> dict[str, list[dict[str, Any]]]:
    value = read_json_file(DISCOVERED_PLATFORM_PROFILES_PATH, {})
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for platform, profiles in value.items():
        if not isinstance(profiles, list):
            continue
        items = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            profile_name = str(profile.get("platform_profile_name") or "").strip()
            if not profile_name:
                continue
            profile_key = str(profile.get("profile_key") or slugify(profile_name))
            items.append(
                {
                    "profile_key": profile_key,
                    "profile_label": str(profile.get("profile_label") or profile_name),
                    "platform_profile_name": profile_name,
                    "is_junior": bool(profile.get("is_junior", False)),
                }
            )
        if items:
            result[str(platform)] = items
    return result


def read_meta_profiles() -> list[dict[str, Any]]:
    value = read_json_file(META_PROFILES_PATH, None)
    if value is None:
        value = read_json_file(PROFILE_MATRIX_CONFIG_PATH, [])
    if not isinstance(value, list):
        return []
    profiles = []
    for item in value:
        if not isinstance(item, dict):
            continue
        platforms = item.get("platforms")
        if platforms is None:
            platforms = item.get("platform_profiles", {})
        profile_key = str(item.get("key", ""))
        profiles.append(
            {
                "key": profile_key,
                "label": str(item.get("label", profile_key)),
                "platforms": platforms if isinstance(platforms, dict) else {},
                "is_junior": bool(item.get("is_junior", False)),
            }
        )
    return profiles


def read_mobile_settings() -> dict[str, Any]:
    value = read_json_file(MOBILE_SETTINGS_PATH, {})
    settings = value if isinstance(value, dict) else {}
    return {
        "sync_alert_hours": clamp_int(settings.get("sync_alert_hours"), 24, 1, 720),
        "sync_alert_enabled": bool(settings.get("sync_alert_enabled", True)),
        "episode_alert_enabled": bool(settings.get("episode_alert_enabled", False)),
        "hide_empty_calendar_days": bool(settings.get("hide_empty_calendar_days", False)),
        "profile_progress_scope": (
            "platform"
            if settings.get("profile_progress_scope") == "platform"
            else "meta"
        ),
    }


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", value.strip().casefold())
    return re.sub(r"_+", "_", cleaned).strip("_")


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def resolve_profile() -> dict[str, Any]:
    meta_profiles = {profile["key"]: profile for profile in read_meta_profiles()}
    if meta_profiles:
        default_key = current_app.config.get("DEFAULT_PROFILE_KEY")
        if default_key not in meta_profiles:
            default_key = next(iter(meta_profiles))
        requested = request.args.get("profile") or request.cookies.get("streaming_profile")
        key = requested if requested in meta_profiles else default_key
        profile = meta_profiles[key]
        return {
            "key": profile["key"],
            "label": profile["label"],
            "technical_id": profile["key"],
            "is_junior": bool(profile.get("is_junior", False)),
            "platforms": profile.get("platforms", {}),
        }
    profiles = current_app.config.get("STREAMING_PROFILES", {})
    default_key = current_app.config.get("DEFAULT_PROFILE_KEY")
    if not profiles:
        abort(500, description="Aucun profil applicatif n'est configuré.")
    if default_key not in profiles:
        default_key = next(iter(profiles))
    requested = request.args.get("profile") or request.cookies.get("streaming_profile")
    key = requested if requested in profiles else default_key
    profile = profiles[key]
    return {
        "key": profile.key,
        "label": profile.label,
        "technical_id": profile.technical_id,
        "is_junior": profile.is_junior,
    }


def append_profile_filter(
    where: list[str],
    params: list[Any],
    *,
    alias: str = "s",
    profile_key: str | None = None,
    junior_only: bool = False,
) -> None:
    if profile_key:
        where.append(f"{alias}.profile_key = ?")
        params.append(profile_key)
    if junior_only:
        where.append(f"COALESCE({alias}.suitable_for_junior, 0) = 1")


def fetch_platforms() -> list[dict[str, Any]]:
    rows = get_db().execute("""
        SELECT COALESCE(plateforme, 'unknown') AS platform, COUNT(*) AS total
        FROM series AS s
        WHERE NOT (s.titre LIKE '__/__/%' OR s.titre LIKE '%Report a problem%')
          AND COALESCE(LOWER(s.imdb_kind), '') NOT IN ('movie', 'film')
        GROUP BY COALESCE(plateforme, 'unknown')
        ORDER BY total DESC, platform
        """).fetchall()
    return [dict(row) for row in rows]


def fetch_movie_platforms() -> list[dict[str, Any]]:
    rows = get_db().execute("""
        SELECT COALESCE(plateforme, 'unknown') AS platform, COUNT(*) AS total
        FROM series AS s
        WHERE LOWER(COALESCE(s.imdb_kind, '')) IN ('movie', 'film')
        GROUP BY COALESCE(plateforme, 'unknown')
        ORDER BY total DESC, platform
        """).fetchall()
    return [dict(row) for row in rows]


def fetch_movies(
    query: str = "",
    platform: str = "",
    genre: str = "",
    profile_key: str | None = None,
    junior_only: bool = False,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ["LOWER(COALESCE(s.imdb_kind, '')) IN ('movie', 'film')"]
    if query:
        where.append("LOWER(s.titre) LIKE LOWER(?)")
        params.append(f"%{query}%")
    if platform:
        where.append("COALESCE(s.plateforme, 'unknown') = ?")
        params.append(platform)
    if genre:
        where.append("LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)")
        params.append(f"%{genre}%")
    append_profile_filter(
        where, params, profile_key=profile_key, junior_only=junior_only
    )
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            s.poster_url,
            COALESCE(s.plateforme, 'unknown') AS plateforme,
            s.synopsis,
            s.creation_year,
            s.imdb_rating,
            s.runtime_minutes,
            COUNT(DISTINCT h.id) AS history_count,
            MAX({VALID_HISTORY_DATE_SQL}) AS last_watched_at,
            MAX(h.created_at) AS last_history_imported_at
        FROM series AS s
        LEFT JOIN history AS h ON h.serie_id = s.id
        WHERE {' AND '.join(where)}
        GROUP BY s.id
        ORDER BY
            (last_watched_at IS NOT NULL) DESC,
            last_watched_at DESC,
            COALESCE(
                last_history_imported_at,
                s.updated_at,
                s.last_updated_at,
                s.titre
            ) DESC,
            s.id DESC
        """ + (" LIMIT ? OFFSET ?" if limit is not None else ""),
            params + ([limit, offset] if limit is not None else []),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def count_movies(
    query: str = "",
    platform: str = "",
    genre: str = "",
    profile_key: str | None = None,
    junior_only: bool = False,
) -> int:
    filters = ["LOWER(COALESCE(s.imdb_kind, '')) IN ('movie', 'film')"]
    params: list[Any] = []
    if query:
        filters.append("LOWER(s.titre) LIKE LOWER(?)")
        params.append(f"%{query}%")
    if platform:
        filters.append("COALESCE(s.plateforme, 'unknown') = ?")
        params.append(platform)
    if genre:
        filters.append("LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)")
        params.append(f"%{genre}%")
    append_profile_filter(
        filters, params, profile_key=profile_key, junior_only=junior_only
    )
    return (
        get_db()
        .execute(
            f"SELECT COUNT(*) FROM series AS s WHERE {' AND '.join(filters)}", params
        )
        .fetchone()[0]
    )


def fetch_movie_stats() -> dict[str, int]:
    conn = get_db()
    return {
        "movies": conn.execute(
            "SELECT COUNT(*) FROM series WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')"
        ).fetchone()[0],
        "platforms": conn.execute(
            """SELECT COUNT(DISTINCT COALESCE(plateforme, 'unknown')) FROM series
               WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')"""
        ).fetchone()[0],
        "history": conn.execute(
            """SELECT COUNT(*) FROM history h JOIN series s ON s.id=h.serie_id
               WHERE LOWER(COALESCE(s.imdb_kind, '')) IN ('movie', 'film')"""
        ).fetchone()[0],
    }


def fetch_admin_series(search_term: str = "") -> list[dict[str, Any]]:
    """Build the series inventory displayed by the local admin page."""
    filters: list[str] = []
    parameters: list[Any] = []
    filters.append(VALID_SERIES_TITLE_SQL)
    if search_term:
        filters.append("s.titre LIKE ?")
        parameters.append(f"%{search_term}%")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            COALESCE(s.plateforme, 'unknown') AS platform,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT c.id) AS calendar_count
        FROM series AS s
        LEFT JOIN history AS h ON h.serie_id = s.id
        LEFT JOIN calendar AS c ON c.serie_id = s.id
        {where_clause}
        GROUP BY s.id
        ORDER BY s.titre COLLATE NOCASE
        """,
            parameters,
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def fetch_admin_movies(search_term: str = "") -> list[dict[str, Any]]:
    filters = ["LOWER(COALESCE(s.imdb_kind, '')) IN ('movie', 'film')"]
    parameters: list[Any] = []
    if search_term:
        filters.append("s.titre LIKE ?")
        parameters.append(f"%{search_term}%")
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            COALESCE(s.plateforme, 'unknown') AS platform,
            COUNT(DISTINCT h.id) AS history_count,
            MAX({VALID_HISTORY_DATE_SQL}) AS last_watched_at
        FROM series AS s
        LEFT JOIN history AS h ON h.serie_id = s.id
        WHERE {' AND '.join(filters)}
        GROUP BY s.id
        ORDER BY s.titre COLLATE NOCASE
        LIMIT 50
        """,
            parameters,
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def fetch_admin_platforms() -> list[dict[str, str]]:
    enabled = current_app.config.get("STREAMING_PLATFORMS", {})
    config_dir = Path("config/platforms")
    platforms = []
    if config_dir.exists():
        for path in sorted(config_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            name = payload.get("name") or path.stem
            if not enabled.get(name, False):
                continue
            platforms.append(
                {"platform": name, "label": PLATFORM_LABELS.get(name, name)}
            )
    return platforms


def backup_database(db_path: Path, reason: str) -> Path:
    backup = (
        db_path.parent
        / "backups"
        / f"streaming-before-{reason}-{datetime.now():%Y%m%d-%H%M%S}.db"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


STATE_DIR = Path(".continue")
ADMIN_RPA_QUEUE = STATE_DIR / "admin_rpa_queue.json"
ADMIN_RPA_QUEUE_LOCK = STATE_DIR / "admin_rpa_queue.lock"
ADMIN_RPA_STATUS = STATE_DIR / "admin_rpa_status.json"
META_PROFILES_PATH = STATE_DIR / "meta_profiles.json"
PROFILE_MATRIX_CONFIG_PATH = Path("config/profile_matrix.local.json")
MOBILE_SETTINGS_PATH = STATE_DIR / "mobile_settings.json"
DISCOVERED_PLATFORM_PROFILES_PATH = STATE_DIR / "platform_profiles_discovered.json"


def enqueue_rpa_platform(
    platform: str, *, profile_key: str | None = None, source: str = "web"
) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job = {
        "id": uuid.uuid4().hex,
        "platform": platform,
        "profile_key": profile_key,
        "source": source,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "log_path": str(Path("logs") / f"admin-rpa-{platform}-{timestamp}.log"),
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    Path(job["log_path"]).parent.mkdir(parents=True, exist_ok=True)
    with locked_admin_rpa_queue():
        queue = read_admin_rpa_queue()
        queue.append(job)
        ADMIN_RPA_QUEUE.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    subprocess.Popen(
        [sys.executable, "-m", "tools.admin_rpa_worker"],
        cwd=Path(__file__).resolve().parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return job


@contextmanager
def locked_admin_rpa_queue():
    with portable_file_lock(ADMIN_RPA_QUEUE_LOCK):
        yield


def read_admin_rpa_queue() -> list[dict[str, Any]]:
    if not ADMIN_RPA_QUEUE.exists():
        return []
    try:
        value = json.loads(ADMIN_RPA_QUEUE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def fetch_admin_rpa_state() -> dict[str, Any]:
    status: dict[str, Any] = {"current": None}
    if ADMIN_RPA_STATUS.exists():
        try:
            loaded = json.loads(ADMIN_RPA_STATUS.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                status.update(loaded)
        except json.JSONDecodeError:
            pass
    with locked_admin_rpa_queue():
        queue = read_admin_rpa_queue()
    current = status.get("current")
    return {
        "current": enrich_rpa_job(current) if isinstance(current, dict) else None,
        "queue": [enrich_rpa_job(job) for job in queue],
        "recent_logs": fetch_admin_rpa_logs(),
    }


def enrich_rpa_job(job: dict[str, Any]) -> dict[str, Any]:
    item = dict(job)
    item["label"] = PLATFORM_LABELS.get(item.get("platform"), item.get("platform"))
    item["log_name"] = Path(item.get("log_path", "")).name
    item["log_tail"] = tail_file(Path(item.get("log_path", "")), lines=80)
    return item


def fetch_admin_rpa_logs(limit: int = 3) -> list[dict[str, Any]]:
    paths = sorted(
        Path("logs").glob("admin-rpa-*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
    return [
        {
            "name": path.name,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "content": tail_file(path, lines=80),
        }
        for path in paths
    ]


def fetch_mobile_ingestion_statuses() -> list[dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT *
        FROM ingestion_runs
        WHERE id IN (
            SELECT MAX(id)
            FROM ingestion_runs
            WHERE platform IS NOT NULL
            GROUP BY platform
        )
        ORDER BY platform
        """
    ).fetchall()
    if rows:
        statuses = {
            row["platform"]: ingestion_run_status(dict(row))
            for row in rows
            if row["platform"]
        }
        for item in fetch_admin_platforms():
            platform = item["platform"]
            statuses.setdefault(
                platform,
                {
                    "platform": platform,
                    "platform_label": item.get("label") or PLATFORM_LABELS.get(platform, platform),
                    "status": "unknown",
                    "inserted": 0,
                    "error": "",
                    "updated_at": "",
                    "started_at": "",
                    "finished_at": "",
                    "duration_seconds": None,
                    "loaded_items_by_profile": {},
                },
            )
        return sorted(statuses.values(), key=lambda item: item["platform_label"])

    statuses: dict[str, dict[str, Any]] = {}
    catalog_summary: dict[str, Any] | None = None
    for timestamp, line in iter_ingestion_log_lines():
        synced = re.search(r"RPA platform synced: ([a-z0-9_]+), inserted=(\d+)", line)
        if synced:
            platform = synced.group(1)
            statuses[platform] = {
                "platform": platform,
                "platform_label": PLATFORM_LABELS.get(platform, platform),
                "status": "ok",
                "inserted": int(synced.group(2)),
                "error": "",
                "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
            continue
        failed = re.search(r"RPA platform sync failed: ([a-z0-9_]+)", line)
        if failed:
            platform = failed.group(1)
            statuses[platform] = {
                "platform": platform,
                "platform_label": PLATFORM_LABELS.get(platform, platform),
                "status": "ko",
                "inserted": 0,
                "error": line.split("|")[-1].strip(),
                "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
            continue
        catalog = re.search(r"Catalog resolution: (\{.*\})", line)
        if catalog:
            catalog_summary = {
                "raw": catalog.group(1),
                "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
    current_admin_platform: str | None = None
    for timestamp, line in iter_admin_rpa_log_lines():
        started = re.search(r"queued job started: ([a-z0-9_]+)", line)
        if started:
            current_admin_platform = started.group(1)
        if "ERROR" in line or "env file" in line or "Traceback" in line:
            platform = _platform_from_admin_log_line(line) or current_admin_platform
            if platform:
                current = statuses.get(platform, {})
                statuses[platform] = {
                    "platform": platform,
                    "platform_label": PLATFORM_LABELS.get(platform, platform),
                    "status": "ko",
                    "inserted": int(current.get("inserted", 0) or 0),
                    "error": _admin_log_error_message(line),
                    "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                }
        finished = re.search(r"queued job finished: ([a-z0-9_]+) rc=(\d+)", line)
        if finished:
            platform = finished.group(1)
            failed = finished.group(2) != "0"
            current = statuses.get(platform, {})
            error = current.get("error", "")
            statuses[platform] = {
                "platform": platform,
                "platform_label": PLATFORM_LABELS.get(platform, platform),
                "status": "ko" if failed else current.get("status", "ok"),
                "inserted": int(current.get("inserted", 0) or 0),
                "error": error if failed else "",
                "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
            continue
        if started:
            platform = started.group(1)
            statuses.setdefault(
                platform,
                {
                    "platform": platform,
                    "platform_label": PLATFORM_LABELS.get(platform, platform),
                    "status": "ok",
                    "inserted": 0,
                    "error": "",
                    "updated_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
    for item in fetch_admin_platforms():
        platform = item["platform"]
        statuses.setdefault(
            platform,
            {
                "platform": platform,
                "platform_label": item.get("label") or PLATFORM_LABELS.get(platform, platform),
                "status": "unknown",
                "inserted": 0,
                "error": "",
                "updated_at": "",
            },
        )
    items = sorted(statuses.values(), key=lambda item: item["platform_label"])
    if catalog_summary is not None:
        has_errors = (
            "'errors': 0" not in catalog_summary["raw"]
            and '"errors": 0' not in catalog_summary["raw"]
        )
        items.append(
            {
                "platform": "catalog",
                "platform_label": "Catalogue",
                "status": "ko" if has_errors else "ok",
                "inserted": 0,
                "error": catalog_summary["raw"] if has_errors else "",
                "updated_at": catalog_summary["updated_at"],
                "summary": catalog_summary["raw"],
            }
        )
    return items


def ingestion_run_status(row: dict[str, Any]) -> dict[str, Any]:
    platform = row.get("platform") or "unknown"
    seconds = float(row.get("duration_seconds") or 0)
    return {
        "id": row.get("id"),
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "profile_key": row.get("profile_key"),
        "source": row.get("source") or "manuel",
        "mode": row.get("mode"),
        "status": row.get("status") or "unknown",
        "inserted": int(row.get("loaded_items") or 0),
        "error": row.get("error") or "",
        "updated_at": row.get("finished_at") or row.get("started_at") or "",
        "started_at": row.get("started_at") or "",
        "finished_at": row.get("finished_at") or "",
        "duration_seconds": seconds,
        "duration": format_duration(seconds),
        "loaded_items_by_profile": parse_json_object(row.get("loaded_items_by_profile")),
    }


def fetch_recent_ingestion_runs(limit_per_platform: int = 5) -> dict[str, list[dict[str, Any]]]:
    rows = get_db().execute(
        """
        SELECT *
        FROM (
            SELECT
                ingestion_runs.*,
                ROW_NUMBER() OVER (
                    PARTITION BY platform
                    ORDER BY datetime(started_at) DESC, id DESC
                ) AS run_rank
            FROM ingestion_runs
            WHERE platform IS NOT NULL
        )
        WHERE run_rank <= ?
        ORDER BY platform, datetime(started_at) DESC, id DESC
        """,
        (limit_per_platform,),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = ingestion_run_status(dict(row))
        grouped.setdefault(item["platform"], []).append(item)
    return grouped


def parse_json_object(raw_value: Any) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _platform_from_admin_log_line(line: str) -> str | None:
    for platform in PLATFORM_LABELS:
        if platform in line:
            return platform
    return None


def _admin_log_error_message(line: str) -> str:
    env_error = re.search(r"(env file .*?)(?: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}|$)", line)
    if env_error:
        return env_error.group(1).strip()
    return line.split("|")[-1].strip()


def tail_file(path: Path, *, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        )
    except OSError:
        return ""


def fetch_recent_ingestion_logs(limit: int = 2, tail_lines: int = 80) -> list[dict[str, Any]]:
    log_dir = Path("logs")
    if not log_dir.exists():
        return []
    paths = sorted(
        log_dir.glob("ingestion.log*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
    logs = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        logs.append(
            {
                "name": path.name,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "content": "\n".join(lines[-tail_lines:]),
            }
        )
    return logs


def fetch_admin_kpis(selected_platform: str | None = None) -> dict[str, Any]:
    conn = get_db()
    series_total = conn.execute(
        f"SELECT COUNT(*) FROM series AS s WHERE {VALID_SERIES_TITLE_SQL}"
    ).fetchone()[0]
    movie_total = conn.execute(
        "SELECT COUNT(*) FROM series WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')"
    ).fetchone()[0]
    platforms = [
        dict(row)
        for row in conn.execute(
            """
        SELECT
            COALESCE(plateforme, 'unknown') AS platform,
            COUNT(*) AS total,
            COUNT(CASE WHEN LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film') THEN 1 END) AS movie_total,
            COUNT(CASE WHEN COALESCE(LOWER(imdb_kind), '') NOT IN ('movie', 'film') THEN 1 END) AS series_total
        FROM series
        GROUP BY COALESCE(plateforme, 'unknown')
        ORDER BY total DESC, platform
        """
        )
    ]
    last_start = latest_ingestion_start()
    added_series = added_movies = 0
    if last_start:
        added_series = conn.execute(
            f"""SELECT COUNT(*) FROM series AS s
                WHERE {VALID_SERIES_TITLE_SQL} AND datetime(updated_at) >= datetime(?)""",
            (last_start.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()[0]
        added_movies = conn.execute(
            """SELECT COUNT(*) FROM series
               WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')
                 AND datetime(updated_at) >= datetime(?)""",
            (last_start.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()[0]
    recent_ingestions = fetch_recent_ingestion_runs(limit_per_platform=5)
    durations = latest_ingestion_durations_from_db(recent_ingestions)
    max_seconds = max([item["seconds"] for item in durations] or [1])
    for item in durations:
        item["percent"] = round((item["seconds"] / max_seconds) * 100, 1)
    return {
        "series_total": series_total,
        "movie_total": movie_total,
        "platform_count": len(platforms),
        "platforms": platforms,
        "added_series": added_series,
        "added_movies": added_movies,
        "last_ingestion_started_at": (
            last_start.strftime("%Y-%m-%d %H:%M:%S") if last_start else None
        ),
        "durations": durations,
        "recent_ingestions": recent_ingestions,
        "selected_platform": selected_platform,
        "selected_platform_titles": fetch_recent_titles_for_platform(
            selected_platform, last_start
        )
        if selected_platform
        else [],
    }


def latest_ingestion_durations_from_db(
    recent_ingestions: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    durations = []
    for platform, runs in recent_ingestions.items():
        if not runs:
            continue
        latest = runs[0]
        seconds = float(latest.get("duration_seconds") or 0)
        durations.append(
            {
                "platform": platform,
                "label": PLATFORM_LABELS.get(platform, platform),
                "seconds": round(seconds, 1),
                "duration": latest.get("duration") or format_duration(seconds),
                "status": "failed" if latest.get("status") == "ko" else "ok",
                "inserted": int(latest.get("inserted") or 0),
            }
        )
    return sorted(durations, key=lambda item: item["seconds"], reverse=True)


def fetch_recent_titles_for_platform(
    platform: str | None, last_start: datetime | None, limit: int = 25
) -> list[dict[str, Any]]:
    if not platform:
        return []
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            COALESCE(s.plateforme, 'unknown') AS platform,
            s.imdb_kind,
            s.updated_at,
            s.poster_url,
            MAX({VALID_HISTORY_DATE_SQL}) AS last_watched_at,
            COUNT(DISTINCT h.id) AS history_count
        FROM series AS s
        LEFT JOIN history AS h ON h.serie_id = s.id
        WHERE COALESCE(s.plateforme, 'unknown') = ?
        GROUP BY s.id
        ORDER BY datetime(s.updated_at) DESC, s.id DESC
        LIMIT ?
        """,
            (platform, limit),
        )
        .fetchall()
    )
    threshold = last_start.strftime("%Y-%m-%d %H:%M:%S") if last_start else None
    titles = []
    for row in rows:
        item = dict(row)
        item["content_type"] = (
            "film"
            if str(item.get("imdb_kind") or "").casefold() in {"movie", "film"}
            else "série"
        )
        item["is_recent"] = bool(
            threshold and item.get("updated_at") and item["updated_at"] >= threshold
        )
        titles.append(item)
    return titles


def latest_ingestion_start() -> datetime | None:
    row = get_db().execute(
        "SELECT started_at FROM ingestion_runs ORDER BY datetime(started_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    if row and row["started_at"]:
        try:
            return datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    starts = [
        timestamp
        for timestamp, line in iter_ingestion_log_lines()
        if "Connecting to Chrome over CDP" in line
        or "Crunchyroll API skipped" in line
        or "Starting RPA platform sync" in line
    ]
    return max(starts) if starts else None


def ingestion_durations_by_platform() -> list[dict[str, Any]]:
    starts: dict[str, datetime] = {}
    latest: dict[str, dict[str, Any]] = {}
    for timestamp, line in iter_ingestion_log_lines():
        start = re.search(r"Starting RPA platform sync: ([a-z0-9_]+)", line)
        if start:
            starts[start.group(1)] = timestamp
            continue
        end = re.search(r"RPA platform synced: ([a-z0-9_]+), inserted=(\d+)", line)
        failed = re.search(r"RPA platform sync failed: ([a-z0-9_]+)", line)
        platform = end.group(1) if end else failed.group(1) if failed else None
        if not platform or platform not in starts:
            continue
        seconds = max(0.0, (timestamp - starts[platform]).total_seconds())
        latest[platform] = {
            "platform": platform,
            "label": PLATFORM_LABELS.get(platform, platform),
            "seconds": round(seconds, 1),
            "duration": format_duration(seconds),
            "status": "failed" if failed else "ok",
            "inserted": int(end.group(2)) if end else None,
        }
    return sorted(latest.values(), key=lambda item: item["seconds"], reverse=True)


def iter_ingestion_log_lines() -> list[tuple[datetime, str]]:
    log_dir = Path("logs")
    if not log_dir.exists():
        return []
    items: list[tuple[datetime, str]] = []
    for path in sorted(log_dir.glob("ingestion.log*")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            timestamp = parse_log_timestamp(line)
            if timestamp:
                items.append((timestamp, line))
    return sorted(items, key=lambda item: item[0])


def iter_admin_rpa_log_lines() -> list[tuple[datetime, str]]:
    log_dir = Path("logs")
    if not log_dir.exists():
        return []
    items: list[tuple[datetime, str]] = []
    for path in sorted(log_dir.glob("admin-rpa-*.log")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        current_timestamp: datetime | None = None
        for line in lines:
            timestamp = parse_admin_log_timestamp(line)
            if timestamp:
                current_timestamp = timestamp
                items.append((timestamp, line))
            elif current_timestamp:
                items.append((current_timestamp, line))
    return sorted(items, key=lambda item: item[0])


def parse_log_timestamp(line: str) -> datetime | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})", line)
    if not match:
        return None
    return datetime.strptime(
        f"{match.group(1)}.{match.group(2)}", "%Y-%m-%d %H:%M:%S.%f"
    )


def parse_admin_log_timestamp(line: str) -> datetime | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    minutes, remaining = divmod(int(round(seconds)), 60)
    if minutes:
        return f"{minutes} min {remaining:02d} s"
    return f"{remaining} s"


def fetch_stats() -> dict[str, int]:
    conn = get_db()
    return {
        "series": conn.execute("SELECT COUNT(*) FROM series").fetchone()[0],
        "calendar": conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0],
        "history": conn.execute("SELECT COUNT(*) FROM history").fetchone()[0],
        "synced": conn.execute(
            "SELECT COUNT(*) FROM history WHERE sync_status = 'synced'"
        ).fetchone()[0],
        "matched": conn.execute(
            "SELECT COUNT(*) FROM history WHERE sync_status = 'matched'"
        ).fetchone()[0],
    }


def fetch_genres(content_type: str = "series") -> list[str]:
    kind_filter = (
        "LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')"
        if content_type == "movie"
        else "COALESCE(LOWER(imdb_kind), '') NOT IN ('movie', 'film')"
    )
    values: set[str] = set()
    for row in get_db().execute(
        f"SELECT genres FROM series WHERE genres IS NOT NULL AND {kind_filter}"
    ):
        values.update(parse_genres(row[0]))
    return sorted(values, key=str.casefold)


def fetch_related_series(
    series_id: int, genres: list[str], limit: int = 12
) -> list[dict[str, Any]]:
    """Return local suggestions sharing at least one known genre."""
    if not genres:
        return []
    rows = (
        get_db()
        .execute(
            """
        SELECT series.id, series.titre, series.poster_url, series.plateforme, series.genres,
               COALESCE(series.seasons_count, COUNT(DISTINCT c.saison)) AS season_count,
               COALESCE(series.episodes_count, COUNT(DISTINCT c.id)) AS episode_count
        FROM series
        LEFT JOIN calendar AS c ON c.serie_id = series.id
        WHERE series.id != ?
        GROUP BY series.id
        ORDER BY titre COLLATE NOCASE
        """,
            (series_id,),
        )
        .fetchall()
    )
    wanted = {genre.casefold() for genre in genres}
    related = []
    for row in rows:
        item = dict(row)
        item["genres_list"] = parse_genres(item.get("genres"))
        score = len(
            wanted.intersection(genre.casefold() for genre in item["genres_list"])
        )
        if score:
            item["match_score"] = score
            related.append(item)
    related.sort(key=lambda item: (-item["match_score"], item["titre"].casefold()))
    return related[:limit]


def search_series(
    query: str = "",
    platform: str = "",
    genre: str = "",
    profile_key: str | None = None,
    junior_only: bool = False,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = [VALID_SERIES_TITLE_SQL]
    if query:
        where.append("LOWER(s.titre) LIKE LOWER(?)")
        params.append(f"%{query}%")
    if platform:
        where.append("COALESCE(s.plateforme, 'unknown') = ?")
        params.append(platform)
    if genre:
        where.append("LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)")
        params.append(f"%{genre}%")
    append_profile_filter(
        where, params, profile_key=profile_key, junior_only=junior_only
    )

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            s.poster_url,
            s.seasons_count,
            s.episodes_count,
            COALESCE(s.plateforme, 'unknown') AS plateforme,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'synced' THEN h.id END) AS synced_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'matched' THEN h.id END) AS matched_count,
            COUNT(DISTINCT c.id) AS calendar_count,
            COUNT(DISTINCT c.saison) AS seasons_count_local,
            COUNT(DISTINCT CASE WHEN c.episode IS NOT NULL THEN c.id END) AS episodes_count_local,
            MIN(CASE WHEN c.date_diffusion >= DATE('now') THEN c.date_diffusion END) AS next_air_date,
            MAX({VALID_HISTORY_DATE_SQL}) AS last_watched_at,
            MAX(h.created_at) AS last_history_imported_at
        FROM series s
        LEFT JOIN history h ON h.serie_id = s.id
        LEFT JOIN calendar c ON c.serie_id = s.id
        {where_sql}
        GROUP BY s.id
        ORDER BY
            (last_watched_at IS NOT NULL) DESC,
            last_watched_at DESC,
            COALESCE(
                last_history_imported_at,
                s.updated_at,
                s.last_updated_at,
                ''
            ) DESC,
            s.id DESC
        """ + (" LIMIT ? OFFSET ?" if limit is not None else ""),
            params + ([limit, offset] if limit is not None else []),
        )
        .fetchall()
    )
    result = [dict(row) for row in rows]
    if result:
        ids = [item["id"] for item in result]
        placeholders = ",".join("?" for _ in ids)
        histories: dict[int, list[dict]] = {}
        for history in get_db().execute(
            f"SELECT * FROM history WHERE serie_id IN ({placeholders})", ids
        ):
            histories.setdefault(history["serie_id"], []).append(dict(history))
        for item in result:
            item["history_count"] = count_watched_episodes(
                histories.get(item["id"], [])
            )
            if has_complete_season_marker(histories.get(item["id"], [])):
                item["history_count"] = (
                    item.get("episodes_count") or item["history_count"]
                )
            item["watched_count"] = item["history_count"]
            item["total_episode_count"] = (
                item["episodes_count"] or item["episodes_count_local"] or None
            )
            item["season_count"] = (
                item["seasons_count"] or item["seasons_count_local"] or None
            )
    return result


def count_series(
    query: str = "",
    platform: str = "",
    genre: str = "",
    profile_key: str | None = None,
    junior_only: bool = False,
) -> int:
    filters = [VALID_SERIES_TITLE_SQL]
    params: list[Any] = []
    if query:
        filters.append("LOWER(s.titre) LIKE LOWER(?)")
        params.append(f"%{query}%")
    if platform:
        filters.append("COALESCE(s.plateforme, 'unknown') = ?")
        params.append(platform)
    if genre:
        filters.append("LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)")
        params.append(f"%{genre}%")
    append_profile_filter(
        filters, params, profile_key=profile_key, junior_only=junior_only
    )
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return (
        get_db()
        .execute(f"SELECT COUNT(*) FROM series AS s {where}", params)
        .fetchone()[0]
    )


def suggest_series(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find titles containing the query, regardless of case."""
    query = query.strip()
    if not query:
        return []
    rows = (
        get_db()
        .execute(
            """
        SELECT id, titre, COALESCE(plateforme, 'unknown') AS platform
        FROM series
        WHERE LOWER(titre) LIKE LOWER(?)
        ORDER BY titre COLLATE NOCASE
        LIMIT ?
        """,
            (f"%{query}%", limit),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def suggest_movies(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    rows = (
        get_db()
        .execute(
            """
        SELECT id, titre, COALESCE(plateforme, 'unknown') AS platform
        FROM series
        WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')
          AND LOWER(titre) LIKE LOWER(?)
        ORDER BY titre COLLATE NOCASE
        LIMIT ?
        """,
            (f"%{query}%", limit),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def fetch_series(series_id: int) -> dict[str, Any] | None:
    row = (
        get_db()
        .execute(
            f"""
        SELECT
            s.*,
            COALESCE(s.plateforme, 'unknown') AS platform,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'synced' THEN h.id END) AS synced_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'matched' THEN h.id END) AS matched_count,
            COUNT(DISTINCT c.id) AS calendar_count,
            MAX({VALID_HISTORY_DATE_SQL}) AS last_watched_at,
            MAX(h.created_at) AS last_history_imported_at,
            MIN(CASE WHEN c.date_diffusion >= DATE('now') THEN c.date_diffusion END) AS next_air_date
        FROM series s
        LEFT JOIN history h ON h.serie_id = s.id
        LEFT JOIN calendar c ON c.serie_id = s.id
        WHERE s.id = ?
        GROUP BY s.id
        """,
            (series_id,),
        )
        .fetchone()
    )
    if not row:
        return None
    series = dict(row)
    sources = (
        get_db()
        .execute(
            """
        SELECT DISTINCT plateforme
        FROM series_sources
        WHERE serie_id = ?
        ORDER BY plateforme
        """,
            (series_id,),
        )
        .fetchall()
    )
    platforms = {series["platform"]}
    platforms.update(source["plateforme"] for source in sources if source["plateforme"])
    series["platforms"] = sorted(platforms)
    return series


def parse_genres(raw_genres: str | None) -> list[str]:
    if not raw_genres:
        return []
    try:
        value = json.loads(raw_genres)
    except json.JSONDecodeError:
        return [part.strip() for part in raw_genres.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item]
    return []


def fetch_calendar(series_id: int, *, only_upcoming: bool) -> list[dict[str, Any]]:
    where = "AND date_diffusion >= DATE('now')" if only_upcoming else ""
    rows = (
        get_db()
        .execute(
            f"""
        SELECT *
        FROM calendar
        WHERE serie_id = ?
          {where}
        ORDER BY date_diffusion ASC, saison ASC, episode ASC
        """,
            (series_id,),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


CALENDAR_PLATFORM_SQL = (
    "COALESCE(NULLIF(s.plateforme, ''), NULLIF(c.plateforme, ''), 'unknown')"
)


def fetch_calendar_platforms(
    month: date, query: str = "", genre: str = ""
) -> list[dict[str, Any]]:
    last_day = month.replace(day=month_calendar.monthrange(month.year, month.month)[1])
    filters = ["DATE(c.date_diffusion) BETWEEN ? AND ?"]
    params: list[Any] = [month.isoformat(), last_day.isoformat()]
    if query:
        filters.append("LOWER(s.titre) LIKE LOWER(?)")
        params.append(f"%{query}%")
    if genre:
        filters.append("LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)")
        params.append(f"%{genre}%")
    rows = (
        get_db()
        .execute(
            f"""SELECT {CALENDAR_PLATFORM_SQL} AS platform,
                   COUNT(DISTINCT s.id) AS series_total, COUNT(DISTINCT c.id) AS episode_total
            FROM series s JOIN calendar c ON s.id=c.serie_id
            WHERE {' AND '.join(filters)}
            GROUP BY platform ORDER BY platform""",
            params,
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def fetch_upcoming_releases(
    month: date,
    _today: date,
    platforms: list[str],
    *,
    watched_filter: str = "all",
    query: str = "",
    genre: str = "",
    profile_key: str | None = None,
    junior_only: bool = False,
) -> list[dict[str, Any]]:
    last_day = month.replace(day=month_calendar.monthrange(month.year, month.month)[1])
    first_day = month
    params: list[Any] = [first_day.isoformat(), last_day.isoformat()]
    platform_filter = ""
    if platforms:
        placeholders = ",".join("?" for _ in platforms)
        platform_filter = f"AND {CALENDAR_PLATFORM_SQL} IN ({placeholders})"
        params.extend(platforms)
    if query:
        platform_filter += " AND LOWER(s.titre) LIKE LOWER(?)"
        params.append(f"%{query}%")
    if genre:
        platform_filter += " AND LOWER(COALESCE(s.genres, '')) LIKE LOWER(?)"
        params.append(f"%{genre}%")
    if profile_key:
        platform_filter += " AND s.profile_key = ?"
        params.append(profile_key)
    if junior_only:
        platform_filter += " AND COALESCE(s.suitable_for_junior, 0) = 1"
    watched_expression = """EXISTS (
        SELECT 1
        FROM history AS watched_history
        WHERE watched_history.serie_id = c.serie_id
          AND watched_history.episode = c.episode
          AND (watched_history.saison = c.saison OR watched_history.saison IS NULL)
          AND COALESCE(watched_history.status, 'watched') NOT IN ('in_progress', 'next_episode')
    )"""
    watched_filter_sql = ""
    if watched_filter == "watched":
        watched_filter_sql = f"AND {watched_expression}"
    elif watched_filter == "unwatched":
        watched_filter_sql = f"AND NOT {watched_expression}"
    rows = (
        get_db()
        .execute(
            f"""SELECT c.*, s.titre AS serie_title, s.poster_url,
                   {CALENDAR_PLATFORM_SQL} AS platform,
                   DATE(c.date_diffusion) AS release_date,
                   {watched_expression} AS watched
            FROM calendar c JOIN series s ON s.id=c.serie_id
            WHERE DATE(c.date_diffusion) BETWEEN ? AND ?
              {platform_filter} {watched_filter_sql}
            ORDER BY release_date, s.titre COLLATE NOCASE, c.saison, c.episode, c.id""",
            params,
        )
        .fetchall()
    )
    seen = set()
    episodes = []
    for row in rows:
        item = dict(row)
        key = (
            item["serie_id"],
            item["saison"],
            item["episode"],
            item["release_date"],
            item["platform"],
        )
        if key not in seen:
            episodes.append(item)
            seen.add(key)
    return episodes


def fetch_history(series_id: int) -> list[dict[str, Any]]:
    rows = (
        get_db()
        .execute(
            """
        SELECT h.*, s.titre AS serie_title
        FROM history AS h
        JOIN series AS s ON s.id = h.serie_id
        WHERE h.serie_id = ?
        ORDER BY
            CASE WHEN date_vu GLOB '????-??-??*' THEN DATE(date_vu) END DESC,
            created_at DESC,
            (saison IS NOT NULL) DESC,
            (sync_status = 'synced') DESC,
            id DESC
        """,
            (series_id,),
        )
        .fetchall()
    )
    result = []
    seen = set()
    for row in rows:
        item = dict(row)
        item["display_title"] = clean_history_title(item)
        identity = episode_identity(item)
        profile_key = item.get("profile_key") or "unknown"
        key = (
            (profile_key, identity, item.get("date_vu"))
            if identity
            else ("row", item["id"])
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def fetch_profile_progress(series_id: int, *, scope: str = "meta") -> list[dict[str, Any]]:
    profile_labels = {profile["key"]: profile["label"] for profile in profile_options()}
    series_row = (
        get_db()
        .execute(
            """
            SELECT COALESCE(plateforme, 'unknown') AS platform,
                   COALESCE(episodes_count, 0) AS episode_count,
                   COALESCE(imdb_kind, '') AS imdb_kind
            FROM series
            WHERE id = ?
            """,
            (series_id,),
        )
        .fetchone()
    )
    platform_key = series_row["platform"] if series_row else "unknown"
    total_episodes = int(series_row["episode_count"] or 0) if series_row else 0
    content_type = (
        "movie"
        if series_row and str(series_row["imdb_kind"]).casefold() in {"movie", "film"}
        else "series"
    )
    platform_profile_labels = platform_profile_labels_for(platform_key)
    rows = (
        get_db()
        .execute(
            """
        SELECT
            COALESCE(h.profile_key, 'unknown') AS profile_key,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT CASE
                WHEN h.saison IS NOT NULL OR h.episode IS NOT NULL
                THEN COALESCE(h.saison, 0) || ':' || COALESCE(h.episode, 0)
            END) AS watched_numbered_episodes,
            MAX(CASE WHEN h.date_vu GLOB '????-??-??*' THEN DATE(h.date_vu) END) AS last_watched_at,
            MAX(h.progress_percent) AS progress_percent,
            MAX(h.status) AS status
        FROM history AS h
        WHERE h.serie_id = ?
        GROUP BY COALESCE(h.profile_key, 'unknown')
        ORDER BY last_watched_at DESC NULLS LAST, profile_key
        """,
            (series_id,),
        )
        .fetchall()
    )
    progress_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        key = item["profile_key"]
        label = profile_labels.get(key, key)
        if scope == "platform":
            label = platform_profile_labels.get(key, label)
            key = f"{platform_key}:{label}"
        watched_episodes = int(item["watched_numbered_episodes"] or 0)
        if watched_episodes <= 0 and int(item["history_count"] or 0) > 0:
            watched_episodes = int(item["history_count"] or 0)
        if int(item["history_count"] or 0) <= 0 and watched_episodes <= 0:
            continue
        previous = progress_by_key.get(key)
        current = {
                "profile_key": key,
                "profile_label": label,
                "content_type": content_type,
                "history_count": int(item["history_count"] or 0),
                "watched_episodes": watched_episodes,
                "episode_count": total_episodes,
                "watched": True,
                "last_watched_at": item["last_watched_at"],
                "progress_percent": item["progress_percent"],
                "status": item["status"],
            }
        if previous is None:
            progress_by_key[key] = current
            continue
        previous["history_count"] += current["history_count"]
        previous["watched_episodes"] += current["watched_episodes"]
        previous["last_watched_at"] = max(
            previous.get("last_watched_at") or "",
            current.get("last_watched_at") or "",
        ) or None
        previous["progress_percent"] = max(
            previous.get("progress_percent") or 0,
            current.get("progress_percent") or 0,
        ) or None
    return sorted(
        progress_by_key.values(),
        key=lambda item: (item.get("last_watched_at") or "", item["profile_label"]),
        reverse=True,
    )


def platform_profile_labels_for(platform: str) -> dict[str, str]:
    labels = {}
    for profile in read_meta_profiles():
        key = str(profile.get("key") or "")
        mapping = profile.get("platforms")
        if not key or not isinstance(mapping, dict):
            continue
        profile_name = str(mapping.get(platform) or "").strip()
        if profile_name:
            labels[key] = profile_name
    return labels


def clean_history_title(item: dict[str, Any]) -> str:
    """Make platform history labels readable before rendering them."""
    raw_value = (item.get("raw_title") or "").strip()
    if raw_value.startswith(("{", "[")):
        try:
            payload = json.loads(raw_value)
            if isinstance(payload, dict):
                raw_value = str(payload.get("text") or payload.get("title") or "")
        except json.JSONDecodeError:
            pass
    raw_title = (item.get("episode_title") or raw_value).strip()
    if not raw_title:
        return item.get("plateforme_source") or "Visionnage"
    cleaned = re.sub(r"^Il reste\s+\d+\s*min(?:utes?)?\s*", "", raw_title, flags=re.I)
    cleaned = re.sub(r"\s*S\d+\s*:?\s*E\d+\s*", " ", cleaned, flags=re.I)
    series_title = (item.get("serie_title") or "").strip()
    if series_title and cleaned.casefold().startswith(series_title.casefold()):
        cleaned = cleaned[len(series_title) :].lstrip(" :-|")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -:|\t")
    return cleaned or raw_title


def has_complete_season_marker(history: list[dict[str, Any]]) -> bool:
    """Recognize Prime's season-level 'episodes watched' history record."""
    return any(
        "épisodes regardés" in (item.get("raw_title") or "").casefold()
        for item in history
    )


def episode_identity(item: dict[str, Any]) -> tuple | None:
    url = item.get("episode_url")
    if url:
        parts = urlsplit(url).path.split("/")
        for marker in ("watch", "play", "episode"):
            if marker in parts and parts.index(marker) + 1 < len(parts):
                return ("url", marker, parts[parts.index(marker) + 1])
    if item.get("betaseries_episode_id"):
        return ("beta", item["betaseries_episode_id"])
    if item.get("episode") is not None:
        return ("episode", item.get("saison"), item["episode"])
    return None


def count_watched_episodes(history: list[dict[str, Any]]) -> int:
    identities = set()
    url_coordinates = {
        episode_identity(item): ("episode", item["saison"], item["episode"])
        for item in history
        if item.get("saison") is not None and item.get("episode") is not None
    }
    episode_coordinates: dict[int, set[tuple]] = {}
    for item in history:
        if item.get("saison") is not None and item.get("episode") is not None:
            episode_coordinates.setdefault(item["episode"], set()).add(
                ("episode", item["saison"], item["episode"])
            )
    for item in history:
        if item.get("status") in {"in_progress", "next_episode"}:
            continue
        key = episode_identity(item)
        if item.get("saison") is not None and item.get("episode") is not None:
            key = ("episode", item["saison"], item["episode"])
        else:
            key = url_coordinates.get(key, key)
            candidates = episode_coordinates.get(item.get("episode"), set())
            if not item.get("episode_url") and len(candidates) == 1:
                key = next(iter(candidates))
        if key:
            identities.add(key)
    return len(identities)


def parse_pagination_args(
    *, default_per_page: int = 20, max_per_page: int = 100
) -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, int(request.args.get("per_page", default_per_page)))
    except ValueError:
        abort(400, description="Paramètre de pagination invalide.")
    return page, min(per_page, max_per_page)


def parse_month(raw_month: str | None) -> date:
    raw_value = raw_month or date.today().strftime("%Y-%m")
    try:
        return datetime.strptime(raw_value, "%Y-%m").date().replace(day=1)
    except ValueError:
        abort(400, description="Le mois doit être au format YYYY-MM.")


def mobile_title_summary(
    item: dict[str, Any], *, content_type: str
) -> dict[str, Any]:
    platform = item.get("plateforme") or item.get("platform") or "unknown"
    return {
        "id": item.get("id"),
        "type": content_type,
        "title": item.get("titre"),
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "poster_url": item.get("poster_url"),
        "synopsis": item.get("synopsis"),
        "season_count": item.get("season_count") or item.get("seasons_count"),
        "episode_count": item.get("total_episode_count")
        or item.get("episodes_count"),
        "watched_count": item.get("watched_count") or item.get("history_count"),
        "next_air_date": item.get("next_air_date"),
        "last_watched_at": item.get("last_watched_at"),
        "year": item.get("creation_year"),
        "rating": item.get("imdb_rating"),
        "runtime_minutes": item.get("runtime_minutes"),
        "profile_key": item.get("profile_key"),
        "suitable_for_junior": bool(item.get("suitable_for_junior")),
        "deep_link_url": fetch_deep_link_url(int(item["id"]), platform=platform),
    }


def mobile_title_detail(
    *,
    serie: dict[str, Any],
    history: list[dict[str, Any]],
    calendar: list[dict[str, Any]],
    upcoming: list[dict[str, Any]],
    status: dict[str, str],
    profile_progress: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    platform = serie.get("platform") or serie.get("plateforme") or "unknown"
    content_type = (
        "movie"
        if str(serie.get("imdb_kind") or "").casefold() in {"movie", "film"}
        else "series"
    )
    return {
        "id": serie.get("id"),
        "type": content_type,
        "title": serie.get("titre"),
        "platform": platform,
        "platforms": serie.get("platforms") or [platform],
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "profile_key": serie.get("profile_key"),
        "suitable_for_junior": bool(serie.get("suitable_for_junior")),
        "poster_url": serie.get("poster_url"),
        "banner_url": serie.get("banner_url"),
        "synopsis": serie.get("synopsis") or serie.get("imdb_plot"),
        "genres": serie.get("genres_list") or parse_genres(serie.get("genres")),
        "season_count": serie.get("seasons_count"),
        "episode_count": serie.get("episodes_count"),
        "watched_count": serie.get("watched_episode_count"),
        "status": status,
        "betaseries_url": serie.get("betaseries_url"),
        "imdb_url": serie.get("imdb_url"),
        "deep_link_url": fetch_deep_link_url(int(serie["id"]), platform=platform),
        "history": [mobile_history_item(item) for item in history],
        "upcoming": [mobile_calendar_episode(item) for item in upcoming],
        "calendar": [mobile_calendar_episode(item) for item in calendar],
        "profile_progress": profile_progress or [],
    }


def mobile_history_item(item: dict[str, Any]) -> dict[str, Any]:
    platform = item.get("plateforme_source") or "unknown"
    profile_key = item.get("profile_key") or "unknown"
    profile_labels = {profile["key"]: profile["label"] for profile in profile_options()}
    return {
        "id": item.get("id"),
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "profile_key": profile_key,
        "profile_label": profile_labels.get(profile_key, profile_key),
        "season": item.get("saison"),
        "episode": item.get("episode"),
        "episode_title": item.get("display_title") or item.get("episode_title"),
        "watched_at": item.get("date_vu"),
        "status": item.get("status"),
        "progress_percent": item.get("progress_percent"),
        "deep_link_url": item.get("episode_url")
        or fetch_platform_fallback_url(platform, item.get("serie_title")),
    }


def mobile_calendar_episode(item: dict[str, Any]) -> dict[str, Any]:
    platform = item.get("platform") or item.get("plateforme") or "unknown"
    return {
        "id": item.get("id"),
        "serie_id": item.get("serie_id"),
        "title": item.get("serie_title"),
        "poster_url": item.get("poster_url") or item.get("image_url"),
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "season": item.get("saison"),
        "episode": item.get("episode"),
        "episode_title": item.get("titre_episode"),
        "release_date": item.get("release_date") or item.get("date_diffusion"),
        "watched": bool(item.get("watched")),
        "deep_link_url": item.get("episode_url")
        or fetch_deep_link_url(int(item["serie_id"]), platform=platform),
    }


def fetch_deep_link_url(series_id: int, *, platform: str | None = None) -> str | None:
    row = (
        get_db()
        .execute(
            """
        SELECT episode_url
        FROM history
        WHERE serie_id = ? AND episode_url IS NOT NULL AND episode_url != ''
        ORDER BY
            CASE WHEN date_vu GLOB '????-??-??*' THEN DATE(date_vu) END DESC,
            created_at DESC,
            id DESC
        LIMIT 1
        """,
            (series_id,),
        )
        .fetchone()
    )
    if row and row["episode_url"]:
        return row["episode_url"]
    row = (
        get_db()
        .execute(
            """
        SELECT episode_url
        FROM calendar
        WHERE serie_id = ? AND episode_url IS NOT NULL AND episode_url != ''
        ORDER BY date_diffusion DESC, id DESC
        LIMIT 1
        """,
            (series_id,),
        )
        .fetchone()
    )
    if row and row["episode_url"]:
        return row["episode_url"]
    serie = fetch_series(series_id)
    if not serie:
        return None
    return fetch_platform_fallback_url(
        platform or serie.get("platform"), serie.get("titre")
    ) or serie.get("betaseries_url") or serie.get("imdb_url")


def fetch_platform_fallback_url(platform: str | None, title: str | None) -> str | None:
    if not platform or not title:
        return None
    from urllib.parse import quote_plus

    encoded_title = quote_plus(title)
    urls = {
        "crunchyroll": f"https://www.crunchyroll.com/fr/search?q={encoded_title}",
        "netflix": f"https://www.netflix.com/search?q={encoded_title}",
        "prime_video": f"https://www.primevideo.com/search/ref=atv_nb_sr?phrase={encoded_title}",
        "disney_plus": f"https://www.disneyplus.com/fr-fr/search/{encoded_title}",
        "canal_plus": f"https://www.canalplus.com/recherche/{encoded_title}",
    }
    return urls.get(platform)


def infer_status(
    serie: dict[str, Any],
    upcoming: list[dict[str, Any]],
    full_calendar: list[dict[str, Any]],
) -> dict[str, str]:
    beta_status = (serie.get("betaseries_status") or "").casefold()
    incoming_season = next_incoming_season(upcoming, full_calendar)
    if incoming_season:
        return {
            "label": "Saison à venir",
            "tone": "good",
            "detail": incoming_season,
        }
    if beta_status in {"continuing", "returning series", "en cours"}:
        if upcoming:
            next_item = upcoming[0]
            return {
                "label": "En cours",
                "tone": "good",
                "detail": f"Nouvel épisode prévu le {next_item.get('date_diffusion')}.",
            }
        return {
            "label": "En cours",
            "tone": "good",
            "detail": "BetaSeries indique que la série est toujours en diffusion.",
        }
    if beta_status in {"ended", "ended/canceled", "canceled", "cancelled", "terminée"}:
        return {
            "label": "Terminée",
            "tone": "muted",
            "detail": "BetaSeries indique que la série est terminée.",
        }
    if upcoming:
        next_item = upcoming[0]
        return {
            "label": "À venir",
            "tone": "good",
            "detail": f"Prochain épisode le {next_item.get('date_diffusion')}.",
        }
    if full_calendar:
        return {
            "label": "Terminée ou à jour",
            "tone": "muted",
            "detail": "Aucune sortie future connue dans la base locale.",
        }
    return {
        "label": "Statut inconnu",
        "tone": "warn",
        "detail": "Aucun calendrier BetaSeries n'est encore associé à cette série.",
    }


def next_incoming_season(
    upcoming: list[dict[str, Any]], full_calendar: list[dict[str, Any]]
) -> str | None:
    if not upcoming:
        return None
    today = date.today()
    past_seasons = []
    for item in full_calendar:
        try:
            release_date = date.fromisoformat(str(item.get("date_diffusion") or ""))
        except ValueError:
            continue
        season = item.get("saison")
        if season is not None and release_date < today:
            past_seasons.append(int(season))
    last_known_season = max(past_seasons or [0])
    next_item = upcoming[0]
    try:
        next_season = int(next_item.get("saison") or 0)
    except (TypeError, ValueError):
        return None
    if next_season <= last_known_season:
        return None
    release_date = next_item.get("date_diffusion")
    if release_date:
        return f"Saison {next_season} is coming le {release_date}."
    return f"Saison {next_season} is coming."


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
