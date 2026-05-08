#!/usr/bin/env python3
"""Background service for automatic dry-run scans + hosted review web UI.

Behavior:
- Starts review_web.py and keeps it running.
- Triggers organize.py in dry-run mode on a fixed interval.
- Restarts the web process if it exits unexpectedly.
"""

from __future__ import annotations

import argparse
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from assistant_config import get_section, load_config, pick, validate_config


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit(message: str) -> None:
    print(f"[{ts()}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run review web UI and periodic organize dry-runs")
    parser.add_argument("--config-file", default="assistant_config.json", help="Path to shared JSON config file")
    parser.add_argument("--input", default=None, help="Inbox directory for organize.py")
    parser.add_argument("--model", default=None, help="Ollama model for organize.py (optional)")
    parser.add_argument("--interval-seconds", type=int, default=None, help="Seconds between dry-run scans")
    parser.add_argument("--host", default=None, help="Host for review_web.py")
    parser.add_argument("--port", type=int, default=None, help="Port for review_web.py")
    parser.add_argument("--state-file", default=None, help="State file for review_web.py")
    parser.add_argument("--field-aliases-file", default=None, help="Shared alias file")
    parser.add_argument("--auth-password", default=None, help="Login password for review_web.py")
    parser.add_argument("--auth-password-file", default=None, help="Password file for review_web.py")
    parser.add_argument("--session-ttl-seconds", type=int, default=None, help="Session lifetime for review_web.py")
    parser.add_argument("--python", default=None, help="Python executable")
    parser.add_argument("--project-dir", default=None, help="Project directory (default: script location)")
    parser.add_argument(
        "--organize-extra-arg",
        action="append",
        default=None,
        help="Extra argument for organize.py (repeatable, e.g. --organize-extra-arg=--ollama-timeout --organize-extra-arg=1800)",
    )
    return parser.parse_args()


def build_review_cmd(args: argparse.Namespace, project_dir: Path) -> list[str]:
    cmd = [
        args.python,
        str(project_dir / "review_web.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--state-file",
        args.state_file,
        "--field-aliases-file",
        args.field_aliases_file,
        "--session-ttl-seconds",
        str(args.session_ttl_seconds),
    ]
    if args.auth_password.strip():
        cmd.extend(["--auth-password", args.auth_password.strip()])
    if args.auth_password_file.strip():
        cmd.extend(["--auth-password-file", args.auth_password_file.strip()])
    return cmd


def build_organize_cmd(args: argparse.Namespace, project_dir: Path) -> list[str]:
    cmd = [
        args.python,
        str(project_dir / "organize.py"),
        "--input",
        args.input,
        "--dry-run",
        "--field-aliases-file",
        args.field_aliases_file,
    ]
    if args.model.strip():
        cmd.extend(["--model", args.model.strip()])

    # Keep this generic for future tuning without code edits.
    cmd.extend(args.organize_extra_arg)
    return cmd


def run_organize_once(args: argparse.Namespace, project_dir: Path) -> int:
    cmd = build_organize_cmd(args, project_dir)
    emit("Run dry-run scan: " + " ".join(shlex.quote(part) for part in cmd))
    proc = subprocess.run(cmd, cwd=str(project_dir), check=False)
    emit(f"Dry-run finished with exit code {proc.returncode}")
    return proc.returncode


def terminate_process(proc: Optional[subprocess.Popen[bytes]], name: str) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return

    emit(f"Stopping {name} (pid={proc.pid})")
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        emit(f"Force-killing {name} (pid={proc.pid})")
        proc.kill()
        proc.wait(timeout=5)


def main() -> int:
    args = parse_args()

    default_project_dir = Path(__file__).resolve().parent
    cfg = load_config(args.config_file, default_project_dir)
    if cfg.errors:
        for err in cfg.errors:
            emit(f"[ERROR] {err}")
        return 2

    config = cfg.data
    validation_errors = validate_config(config)
    if validation_errors:
        for err in validation_errors:
            emit(f"[ERROR] Invalid config: {err}")
        return 2

    section = get_section(config, "service")

    args.input = str(pick(args.input, section, "input", "")).strip()
    args.model = str(pick(args.model, section, "model", "")).strip()
    args.interval_seconds = int(pick(args.interval_seconds, section, "interval_seconds", 300))
    args.host = str(pick(args.host, section, "host", "127.0.0.1")).strip()
    args.port = int(pick(args.port, section, "port", 8765))
    args.state_file = str(pick(args.state_file, section, "state_file", "review_state.json")).strip()
    args.field_aliases_file = str(pick(args.field_aliases_file, section, "field_aliases_file", "field_aliases.json")).strip()
    args.auth_password = str(pick(args.auth_password, section, "auth_password", "")).strip()
    args.auth_password_file = str(pick(args.auth_password_file, section, "auth_password_file", "")).strip()
    args.session_ttl_seconds = int(pick(args.session_ttl_seconds, section, "session_ttl_seconds", 28800))
    args.python = str(pick(args.python, section, "python", sys.executable)).strip()
    args.project_dir = str(pick(args.project_dir, section, "project_dir", "")).strip()
    if args.organize_extra_arg is None:
        cfg_extra = section.get("organize_extra_args", [])
        args.organize_extra_arg = [str(v) for v in cfg_extra] if isinstance(cfg_extra, list) else []

    if not args.input:
        emit("[ERROR] Missing input folder. Set --input or service.input in assistant_config.json")
        return 2

    if args.interval_seconds < 30:
        emit("interval-seconds too low; using minimum of 30")
        args.interval_seconds = 30

    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else default_project_dir
    if not (project_dir / "organize.py").exists() or not (project_dir / "review_web.py").exists():
        emit(f"[ERROR] project-dir invalid: {project_dir}")
        return 2

    stop = {"value": False}

    def on_signal(signum: int, _frame: object) -> None:
        emit(f"Signal {signum} received, shutting down...")
        stop["value"] = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    review_proc: Optional[subprocess.Popen[bytes]] = None

    emit(f"Service start. project_dir={project_dir}")
    emit(f"Web UI: http://{args.host}:{args.port}")
    emit(f"Scan interval: {args.interval_seconds}s")

    try:
        next_scan_at = 0.0
        while not stop["value"]:
            if review_proc is None or review_proc.poll() is not None:
                if review_proc is not None:
                    emit(f"review_web.py exited with code {review_proc.returncode}, restarting...")
                review_cmd = build_review_cmd(args, project_dir)
                emit("Starting review web: " + " ".join(shlex.quote(part) for part in review_cmd))
                review_proc = subprocess.Popen(review_cmd, cwd=str(project_dir))

            now = time.time()
            if now >= next_scan_at:
                run_organize_once(args, project_dir)
                next_scan_at = now + float(args.interval_seconds)

            time.sleep(1.0)
    finally:
        terminate_process(review_proc, "review_web.py")

    emit("Service stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
