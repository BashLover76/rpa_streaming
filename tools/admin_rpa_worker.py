from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ingestion.runtime_platform import portable_file_lock


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".continue"
QUEUE_FILE = STATE_DIR / "admin_rpa_queue.json"
QUEUE_LOCK = STATE_DIR / "admin_rpa_queue.lock"
WORKER_LOCK = STATE_DIR / "admin_rpa_worker.lock"
STATUS_FILE = STATE_DIR / "admin_rpa_status.json"


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with portable_file_lock(WORKER_LOCK):
            run_until_queue_empty()
    except SystemExit:
        return


def run_until_queue_empty() -> None:
    while True:
        job = pop_job()
        if job is None:
            write_status({"current": None, "updated_at": now()})
            return
        run_job(job)


def run_job(job: dict[str, Any]) -> None:
    job["started_at"] = now()
    write_status({"current": job, "updated_at": now()})
    log_path = ROOT / job["log_path"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_rpa_command(job["platform"])
    with log_path.open("ab") as log_file:
        log_file.write(
            f"{now()} | INFO | admin_rpa_worker | queued job started: {job['platform']}\n".encode()
        )
        log_file.flush()
        return_code = subprocess.call(
            command,
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.write(
            f"{now()} | INFO | admin_rpa_worker | queued job finished: {job['platform']} rc={return_code}\n".encode()
        )
    job["finished_at"] = now()
    job["return_code"] = return_code
    write_status({"current": None, "last_completed": job, "updated_at": now()})


def build_rpa_command(platform: str) -> list[str]:
    runner = os.getenv("ADMIN_RPA_RUNNER", "local").strip().casefold()
    if runner == "docker":
        compose_file = os.getenv("ADMIN_RPA_COMPOSE_FILE", "docker-compose.rpa.yml")
        service = os.getenv("ADMIN_RPA_DOCKER_SERVICE", "rpa-job")
        return [
            "docker",
            "compose",
            "-f",
            compose_file,
            "run",
            "--build",
            "--rm",
            service,
            "python",
            "main_ingestion.py",
            "--platform",
            platform,
            "--cdp-url",
            os.getenv("ADMIN_RPA_CDP_URL", "http://127.0.0.1:9222"),
            "--rpa-mode",
            "differential",
            "--all-profiles",
            "--skip-crunchyroll-api",
            "--no-auto-start-chrome",
        ]
    if runner == "command":
        template = os.getenv("ADMIN_RPA_COMMAND_TEMPLATE", "").strip()
        if not template:
            raise RuntimeError(
                "ADMIN_RPA_COMMAND_TEMPLATE is required when ADMIN_RPA_RUNNER=command"
            )
        return shlex.split(template.format(platform=platform))
    return [
        sys.executable,
        "main_ingestion.py",
        "--platform",
        platform,
        "--cdp-url",
        os.getenv("RPA_CDP_URL", "http://127.0.0.1:9222"),
        "--rpa-mode",
        "differential",
        "--all-profiles",
        "--skip-crunchyroll-api",
        "--no-auto-start-chrome",
    ]


def pop_job() -> dict[str, Any] | None:
    with locked_queue():
        queue = read_queue()
        if not queue:
            return None
        job = queue.pop(0)
        write_queue(queue)
        return job


def locked_queue():
    return portable_file_lock(QUEUE_LOCK)


def read_queue() -> list[dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    try:
        value = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def write_queue(queue: list[dict[str, Any]]) -> None:
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(status: dict[str, Any]) -> None:
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    main()
