from __future__ import annotations

import calendar as month_calendar
import hmac
import json
import re
import sqlite3
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

PLATFORM_MARKS = {
    "canal_plus": "C+",
    "crunchyroll": "CR",
    "disney_plus": "D+",
    "netflix": "N",
    "prime_video": "PV",
    "unknown": "BS",
}


def create_app() -> Flask:
    app = Flask(__name__)
    settings = Settings.from_env()
    app.config["DB_PATH"] = settings.db_path
    app.config["ADMIN_TOKEN"] = settings.admin_token

    @app.teardown_appcontext
    def close_db(_error: BaseException | None = None) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def protect_admin_routes():
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

    @app.get("/")
    def index():
        query = request.args.get("q", "").strip()
        selected_platform = request.args.get("platform", "").strip()
        selected_genre = request.args.get("genre", "").strip()
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
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_series = count_series(query, selected_platform, selected_genre)
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
        )

    @app.get("/series/<int:series_id>")
    def series_detail(series_id: int):
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
        )

    @app.get("/admin")
    def admin_view():
        query = request.args.get("q", "").strip()
        return render_template(
            "admin.html",
            series=fetch_admin_series(query),
            query=query,
            platform_labels=PLATFORM_LABELS,
        )

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
            url_for("admin_view", deleted=counts["series"], backup=backup.name)
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
        )

    @app.get("/api/series/suggest")
    def series_suggestions():
        return jsonify(suggest_series(request.args.get("q", "")))

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DB_PATH"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


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


def fetch_admin_series(search_term: str = "") -> list[dict[str, Any]]:
    """Build the series inventory displayed by the local admin page."""
    filters: list[str] = []
    parameters: list[Any] = []
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


def fetch_genres() -> list[str]:
    values: set[str] = set()
    for row in get_db().execute("SELECT genres FROM series WHERE genres IS NOT NULL"):
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
            MIN(CASE WHEN c.date_diffusion >= DATE('now') THEN c.date_diffusion END) AS next_air_date
        FROM series s
        LEFT JOIN history h ON h.serie_id = s.id
        LEFT JOIN calendar c ON c.serie_id = s.id
        {where_sql}
        GROUP BY s.id
        ORDER BY
            CASE WHEN next_air_date IS NULL THEN 1 ELSE 0 END,
            next_air_date ASC,
            s.titre COLLATE NOCASE ASC
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


def count_series(query: str = "", platform: str = "", genre: str = "") -> int:
    filters = ["NOT (s.titre LIKE '__/__/%' OR s.titre LIKE '%Report a problem%')"]
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


def fetch_series(series_id: int) -> dict[str, Any] | None:
    row = (
        get_db()
        .execute(
            """
        SELECT
            s.*,
            COALESCE(s.plateforme, 'unknown') AS platform,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'synced' THEN h.id END) AS synced_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'matched' THEN h.id END) AS matched_count,
            COUNT(DISTINCT c.id) AS calendar_count,
            MAX(h.date_vu) AS last_watched_at,
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
        ORDER BY date_vu DESC, (saison IS NOT NULL) DESC, (sync_status = 'synced') DESC, created_at DESC, id DESC
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
        key = (identity, item.get("date_vu")) if identity else ("row", item["id"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


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


def infer_status(
    serie: dict[str, Any],
    upcoming: list[dict[str, Any]],
    full_calendar: list[dict[str, Any]],
) -> dict[str, str]:
    beta_status = (serie.get("betaseries_status") or "").casefold()
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


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
