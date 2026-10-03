"""Backfill legacy profile keys after enabling multi-profile ingestion."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Attach legacy rows to a selected meta-profile. By default this is a "
            "dry run and only prints the affected counts."
        )
    )
    parser.add_argument("--db", default="streaming.db", help="SQLite database path.")
    parser.add_argument(
        "--platform",
        required=True,
        help="Streaming platform key, for example crunchyroll.",
    )
    parser.add_argument(
        "--target-profile",
        required=True,
        help="Meta-profile key to assign, for example chris.",
    )
    parser.add_argument(
        "--from-profile",
        action="append",
        default=[],
        help=(
            "Legacy profile key to migrate. Can be repeated. "
            "Example: --from-profile default"
        ),
    )
    parser.add_argument(
        "--include-null",
        action="store_true",
        help="Also migrate rows where profile_key is NULL.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the update. Without this flag the script is read-only.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    predicates, parameters = profile_predicate(args.from_profile, args.include_null)
    if not predicates:
        raise SystemExit("Nothing to migrate: pass --from-profile and/or --include-null.")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        series_count = count_rows(
            connection,
            table="series",
            platform_column="plateforme",
            platform=args.platform,
            predicates=predicates,
            parameters=parameters,
        )
        history_count = count_rows(
            connection,
            table="history",
            platform_column="plateforme_source",
            platform=args.platform,
            predicates=predicates,
            parameters=parameters,
        )
        print(
            f"{args.platform}: series={series_count}, history={history_count}, "
            f"target_profile={args.target_profile}"
        )
        if not args.apply:
            print("Dry run only. Re-run with --apply to update the database.")
            return

        backup_path = backup_database(db_path)
        print(f"Backup created: {backup_path}")
        update_rows(
            connection,
            table="series",
            platform_column="plateforme",
            platform=args.platform,
            target_profile=args.target_profile,
            predicates=predicates,
            parameters=parameters,
        )
        update_rows(
            connection,
            table="history",
            platform_column="plateforme_source",
            platform=args.platform,
            target_profile=args.target_profile,
            predicates=predicates,
            parameters=parameters,
        )
        connection.commit()
        print("Profile backfill complete.")


def profile_predicate(
    profile_keys: list[str], include_null: bool
) -> tuple[list[str], list[str]]:
    predicates = []
    parameters = []
    if profile_keys:
        placeholders = ", ".join("?" for _ in profile_keys)
        predicates.append(f"profile_key IN ({placeholders})")
        parameters.extend(profile_keys)
    if include_null:
        predicates.append("profile_key IS NULL")
    return predicates, parameters


def count_rows(
    connection: sqlite3.Connection,
    *,
    table: str,
    platform_column: str,
    platform: str,
    predicates: list[str],
    parameters: list[str],
) -> int:
    sql = f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE {platform_column} = ?
          AND ({' OR '.join(predicates)})
    """
    return int(connection.execute(sql, [platform, *parameters]).fetchone()[0])


def update_rows(
    connection: sqlite3.Connection,
    *,
    table: str,
    platform_column: str,
    platform: str,
    target_profile: str,
    predicates: list[str],
    parameters: list[str],
) -> None:
    sql = f"""
        UPDATE {table}
        SET profile_key = ?
        WHERE {platform_column} = ?
          AND ({' OR '.join(predicates)})
    """
    connection.execute(sql, [target_profile, platform, *parameters])


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / (
        f"{db_path.stem}-before-profile-backfill-"
        f"{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}"
    )
    shutil.copy2(db_path, backup_path)
    return backup_path


if __name__ == "__main__":
    main()
