from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

UNITS = [
    "rpa-streaming-full.service",
    "rpa-streaming-full.timer",
    "rpa-streaming-differential.service",
    "rpa-streaming-differential.timer",
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "ops" / "systemd"
    target = Path.home() / ".config" / "systemd" / "user"
    target.mkdir(parents=True, exist_ok=True)

    for unit in UNITS:
        shutil.copy2(source / unit, target / unit)
        print(f"installed {target / unit}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "rpa-streaming-full.timer"],
        check=True,
    )
    subprocess.run(
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "rpa-streaming-differential.timer",
        ],
        check=True,
    )
    subprocess.run(
        ["systemctl", "--user", "list-timers", "rpa-streaming-*"], check=True
    )


if __name__ == "__main__":
    main()
