from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.runtime_platform import detect_runtime_platform


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install system and Python dependencies for rpa_streaming."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-ollama", action="store_true")
    args = parser.parse_args()
    runtime = detect_runtime_platform()
    print(
        f"Detected OS: system={runtime.system} windows={runtime.is_windows} "
        f"linux={runtime.is_linux} wsl={runtime.is_wsl}"
    )
    if runtime.is_windows:
        install_windows(args.dry_run, args.with_ollama)
    elif runtime.is_linux:
        install_linux(args.dry_run, args.with_ollama, wsl=runtime.is_wsl)
    else:
        raise SystemExit(f"Unsupported OS: {runtime.system}")
    install_python_stack(args.dry_run)


def install_windows(dry_run: bool, with_ollama: bool) -> None:
    if shutil.which("winget") is None:
        print("winget not found. Install Python 3.12+, Git and Google Chrome manually.")
        return
    packages = [
        ["winget", "install", "-e", "--id", "Python.Python.3.12"],
        ["winget", "install", "-e", "--id", "Git.Git"],
        ["winget", "install", "-e", "--id", "Google.Chrome"],
    ]
    if with_ollama:
        packages.append(["winget", "install", "-e", "--id", "Ollama.Ollama"])
    for command in packages:
        run(command, dry_run=dry_run)


def install_linux(dry_run: bool, with_ollama: bool, *, wsl: bool) -> None:
    if shutil.which("apt-get"):
        run(["sudo", "apt-get", "update"], dry_run=dry_run)
        run(
            [
                "sudo",
                "apt-get",
                "install",
                "-y",
                "python3",
                "python3-venv",
                "python3-pip",
                "git",
                "curl",
                "ca-certificates",
                "sqlite3",
            ],
            dry_run=dry_run,
        )
        if not wsl:
            install_chrome_linux_apt(dry_run)
    else:
        print("No apt-get found. Install Python, pip, git, curl, sqlite3 and Chrome manually.")
    if with_ollama:
        run_shell("curl -fsSL https://ollama.com/install.sh | sh", dry_run=dry_run)


def install_chrome_linux_apt(dry_run: bool) -> None:
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        return
    run_shell(
        "wget -q -O - https://dl.google.com/linux/linux_signing_key.pub "
        "| sudo gpg --dearmor -o /usr/share/keyrings/google-linux-signing-keyring.gpg",
        dry_run=dry_run,
    )
    run_shell(
        "echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-signing-keyring.gpg] "
        "http://dl.google.com/linux/chrome/deb/ stable main' "
        "| sudo tee /etc/apt/sources.list.d/google-chrome.list",
        dry_run=dry_run,
    )
    run(["sudo", "apt-get", "update"], dry_run=dry_run)
    run(["sudo", "apt-get", "install", "-y", "google-chrome-stable"], dry_run=dry_run)


def install_python_stack(dry_run: bool) -> None:
    python = Path(".venv/Scripts/python.exe") if os.name == "nt" else Path(".venv/bin/python")
    if not python.exists():
        run([sys.executable, "-m", "venv", ".venv"], dry_run=dry_run, cwd=ROOT)
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run, cwd=ROOT)
    run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], dry_run=dry_run, cwd=ROOT)
    if Path(ROOT / "requirements-dev.txt").exists():
        run([str(python), "-m", "pip", "install", "-r", "requirements-dev.txt"], dry_run=dry_run, cwd=ROOT)
    run([str(python), "-m", "playwright", "install", "chromium"], dry_run=dry_run, cwd=ROOT)


def run(command: list[str], *, dry_run: bool, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    if not dry_run:
        subprocess.run(command, cwd=cwd, check=True)


def run_shell(command: str, *, dry_run: bool) -> None:
    print("+", command)
    if not dry_run:
        subprocess.run(command, shell=True, check=True)


if __name__ == "__main__":
    main()
