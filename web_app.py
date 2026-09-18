from __future__ import annotations

import calendar as month_calendar
import json
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


def create_app() -> Flask:
    app = Flask(__name__)
    settings = Settings.from_env()
    app.config["DB_PATH"] = settings.db_path

    @app.teardown_appcontext
    def close_db(_error: BaseException | None = None) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.get("/")
    def index():
        query = request.args.get("q", "").strip()
        selected_platform = request.args.get("platform", "").strip()
        platforms = fetch_platforms()
        series = search_series(query=query, platform=selected_platform)
        stats = fetch_stats()
        return render_template(
            "index.html",
            query=query,
            selected_platform=selected_platform,
            platforms=platforms,
            platform_labels=PLATFORM_LABELS,
            series=series,
            stats=stats,
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
        serie["genres_list"] = parse_genres(serie.get("genres"))
        status = infer_status(serie, upcoming, full_calendar)
        return render_template(
            "series_detail.html",
            serie=serie,
            platform_labels=PLATFORM_LABELS,
            upcoming=upcoming,
            full_calendar=full_calendar,
            history=history[:50],
            status=status,
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
        selected = list(dict.fromkeys(request.args.getlist("platform")))
        options = fetch_calendar_platforms(today)
        episodes = fetch_upcoming_releases(month, today, selected)
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
            selected_platforms=selected,
            platform_labels=PLATFORM_LABELS,
            episode_count=len(episodes),
            previous_month=previous.strftime("%Y-%m"),
            next_month=following.strftime("%Y-%m"),
        )

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
        FROM series
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


def search_series(query: str = "", platform: str = "") -> list[dict[str, Any]]:
    params: list[Any] = []
    where = []
    if query:
        where.append("s.titre LIKE ?")
        params.append(f"%{query}%")
    if platform:
        where.append("COALESCE(s.plateforme, 'unknown') = ?")
        params.append(platform)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = (
        get_db()
        .execute(
            f"""
        SELECT
            s.id,
            s.titre,
            s.poster_url,
            COALESCE(s.plateforme, 'unknown') AS plateforme,
            COUNT(DISTINCT h.id) AS history_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'synced' THEN h.id END) AS synced_count,
            COUNT(DISTINCT CASE WHEN h.sync_status = 'matched' THEN h.id END) AS matched_count,
            COUNT(DISTINCT c.id) AS calendar_count,
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
        """,
            params,
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
    return result


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
    return dict(row) if row else None


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


def fetch_calendar_platforms(today: date) -> list[dict[str, Any]]:
    rows = (
        get_db()
        .execute(
            f"""SELECT {CALENDAR_PLATFORM_SQL} AS platform, COUNT(c.id) AS total
            FROM series s LEFT JOIN calendar c ON s.id=c.serie_id AND DATE(c.date_diffusion)>=?
            GROUP BY platform ORDER BY platform""",
            (today.isoformat(),),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


def fetch_upcoming_releases(
    month: date, today: date, platforms: list[str]
) -> list[dict[str, Any]]:
    last_day = month.replace(day=month_calendar.monthrange(month.year, month.month)[1])
    params: list[Any] = [max(month, today).isoformat(), last_day.isoformat()]
    platform_filter = ""
    if platforms:
        placeholders = ",".join("?" for _ in platforms)
        platform_filter = f"AND {CALENDAR_PLATFORM_SQL} IN ({placeholders})"
        params.extend(platforms)
    rows = (
        get_db()
        .execute(
            f"""SELECT c.*, s.titre AS serie_title, s.poster_url,
                   {CALENDAR_PLATFORM_SQL} AS platform, DATE(c.date_diffusion) AS release_date
            FROM calendar c JOIN series s ON s.id=c.serie_id
            WHERE DATE(c.date_diffusion) BETWEEN ? AND ? {platform_filter}
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
        SELECT *
        FROM history
        WHERE serie_id = ?
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
        identity = episode_identity(item)
        key = (identity, item.get("date_vu")) if identity else ("row", item["id"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


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
