from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the local SQLite database into the Docker web container."
    )
    parser.add_argument("--db", type=Path, default=Path("streaming.db"))
    parser.add_argument("--container", default="streaming-web")
    parser.add_argument("--target", default="/data/streaming.db")
    parser.add_argument("--restart", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    subprocess.run(
        ["docker", "cp", str(args.db), f"{args.container}:{args.target}"],
        check=True,
    )
    if args.restart:
        subprocess.run(["docker", "restart", args.container], check=True)
    print(f"Copied {args.db} to {args.container}:{args.target}")


if __name__ == "__main__":
    main()
