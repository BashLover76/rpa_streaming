from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy local config files into the Docker config volume."
    )
    parser.add_argument("--source", type=Path, default=Path("config"))
    parser.add_argument(
        "--volume",
        default="rpa_streaming_streaming-web-config",
    )
    parser.add_argument("--helper", default="streaming-config-copy")
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def run_best_effort(command: list[str]) -> None:
    subprocess.run(command, check=False)


def main() -> None:
    args = parse_args()
    source = args.source
    if not source.is_dir():
        raise SystemExit(f"Config directory not found: {source}")

    run(["docker", "volume", "create", args.volume])
    run_best_effort(["docker", "rm", "-f", args.helper])
    run(
        [
            "docker",
            "create",
            "--name",
            args.helper,
            "-v",
            f"{args.volume}:/config-volume",
            "alpine:latest",
            "sh",
        ]
    )
    try:
        run(["docker", "cp", f"{source}/.", f"{args.helper}:/config-volume"])
    finally:
        run_best_effort(["docker", "rm", "-f", args.helper])
    print(f"Copied {source} to Docker volume {args.volume}")


if __name__ == "__main__":
    main()
