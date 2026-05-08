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


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit(message: str) -> None:
    print(f"[{ts()}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run review web UI and periodic organize dry-runs")
    parser.add_argument("--input", required=True, help="Inbox directory for organize.py")
    parser.add_argument("--model", default="", help="Ollama model for organize.py (optional)")
    parser.add_argument("--interval-seconds", type=int, default=300, help="Seconds between dry-run scans")
    parser.add_argument("--host", default="127.0.0.1", help="Host for review_web.py")
    parser.add_argument("--port", type=int, default=8765, help="Port for review_web.py")
    parser.add_argument("--state-file", default="review_state.json", help="State file for review_web.py")
    parser.add_argument("--field-aliases-file", default="field_aliases.json", help="Shared alias file")
    parser.add_argument("--auth-password", default="", help="Login password for review_web.py")
    parser.add_argument("--auth-password-file", default="", help="Password file for review_web.py")
    parser.add_argument("--session-ttl-seconds", type=int, default=28800, help="Session lifetime for review_web.py")
    parser.add_argument("--python", default=sys.executable, help="Python executable")
    parser.add_argument("--project-dir", default="", help="Project directory (default: script location)")
    parser.add_argument(
        "--organize-extra-arg",
        action="append",
        default=[],
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

    if args.interval_seconds < 30:
        emit("interval-seconds too low; using minimum of 30")
        args.interval_seconds = 30

    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else Path(__file__).resolve().parent
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
