from __future__ import annotations

import sqlite3


def main() -> None:
    con = sqlite3.connect("streaming.db")
    stats = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ["series", "calendar", "history"]
    }
    stats["crunchyroll_series"] = con.execute(
        "SELECT COUNT(*) FROM series WHERE plateforme = 'crunchyroll'"
    ).fetchone()[0]
    stats["crunchyroll_history"] = con.execute(
        "SELECT COUNT(*) FROM history WHERE plateforme_source = 'crunchyroll'"
    ).fetchone()[0]
    stats["canal_plus_series"] = con.execute(
        "SELECT COUNT(*) FROM series WHERE plateforme = 'canal_plus'"
    ).fetchone()[0]
    stats["canal_plus_history"] = con.execute(
        "SELECT COUNT(*) FROM history WHERE plateforme_source = 'canal_plus'"
    ).fetchone()[0]
    for platform in ["netflix", "prime_video", "disney_plus"]:
        stats[f"{platform}_series"] = con.execute(
            "SELECT COUNT(*) FROM series WHERE plateforme = ?", (platform,)
        ).fetchone()[0]
        stats[f"{platform}_history"] = con.execute(
            "SELECT COUNT(*) FROM history WHERE plateforme_source = ?", (platform,)
        ).fetchone()[0]
    con.close()
    print(stats)


if __name__ == "__main__":
    main()
