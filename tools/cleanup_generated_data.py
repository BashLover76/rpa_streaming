from __future__ import annotations

import sqlite3


def main() -> None:
    con = sqlite3.connect("streaming.db")
    deleted = con.execute("""
        DELETE FROM series
        WHERE plateforme = 'crunchyroll'
          AND titre GLOB '[0-9]* de *'
        """).rowcount
    orphan_history = con.execute("""
        DELETE FROM history
        WHERE serie_id NOT IN (SELECT id FROM series)
        """).rowcount
    disney_bad_titles = con.execute("""
        DELETE FROM series
        WHERE plateforme = 'disney_plus'
          AND (
            titre LIKE 'min%'
            OR titre LIKE 'Il reste%'
            OR titre LIKE 'Épisode suivant%'
            OR titre GLOB '*[0-9][0-9][0-9][0-9]•*'
          )
        """).rowcount
    con.commit()
    con.close()
    print(
        {
            "deleted_false_crunchyroll_titles": deleted,
            "deleted_orphan_history": orphan_history,
            "deleted_bad_disney_titles": disney_bad_titles,
        }
    )


if __name__ == "__main__":
    main()
