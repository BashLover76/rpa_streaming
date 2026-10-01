from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the exported browser storage_state into the RPA Docker state volume."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(".continue/browser-storage-state.json"),
        help="Local storage_state JSON produced by tools.export_chrome_storage_state.",
    )
    parser.add_argument(
        "--volume",
        default="rpa_streaming_rpa-state",
        help="Docker volume mounted as /app/.continue by RPA jobs.",
    )
    parser.add_argument(
        "--target-name",
        default="browser-storage-state.json",
        help="File name to write inside the Docker volume.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.source.exists():
        raise SystemExit(f"storage_state source not found: {args.source}")

    container_name = "rpa-storage-state-sync"
    subprocess.run(
        [
            "docker",
            "run",
            "--name",
            container_name,
            "-v",
            f"{args.volume}:/state",
            "busybox",
            "sh",
            "-c",
            "mkdir -p /state && sleep 1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        subprocess.run(
            [
                "docker",
                "cp",
                str(args.source),
                f"{container_name}:/state/{args.target_name}",
            ],
            check=True,
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    print(f"storage_state copied to volume {args.volume}:{args.target_name}")


if __name__ == "__main__":
    main()
