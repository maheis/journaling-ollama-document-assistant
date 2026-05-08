#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_SYSTEMD=1
START_SERVICE=1
INSTALL_SYSTEM_DEPS=0
INSTALL_OLLAMA=0
PULL_MODELS=0
MODEL_OVERRIDE=""

print_usage() {
  cat <<'USAGE'
Usage: bash ./install.sh [options]

Options:
  --full-setup         Enable: --install-system-deps --install-ollama --pull-models
  --install-system-deps
                       Install required Debian/Ubuntu packages via apt-get
  --install-ollama     Install Ollama and try to start/enable service
  --pull-models        Pull model(s) in Ollama (from config or --model)
  --model <name>       Model name to pull (repeatable by comma: m1,m2)
  --no-systemd         Do not install user systemd unit
  --no-start           Install unit but do not start/restart it
  --help               Show this help

Examples:
  bash ./install.sh
  bash ./install.sh --full-setup
  bash ./install.sh --install-system-deps --install-ollama --pull-models --model qwen2.5:7b-instruct
USAGE
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  echo "[ERROR] Root privileges required for: $* (sudo not found)" >&2
  exit 2
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

ensure_assistant_config() {
  if [[ -f "$PROJECT_DIR/assistant_config.json" ]]; then
    return
  fi
  cat > "$PROJECT_DIR/assistant_config.json" <<'JSON'
{
  "review_web": {
    "host": "127.0.0.1",
    "port": 8765,
    "state_file": "review_state.json",
    "field_aliases_file": "field_aliases.json",
    "auth_password_file": ".review_web_password",
    "session_ttl_seconds": 28800
  },
  "service": {
    "input": "./inbox",
    "model": "qwen2.5:7b-instruct",
    "interval_seconds": 300,
    "host": "127.0.0.1",
    "port": 8765,
    "state_file": "review_state.json",
    "field_aliases_file": "field_aliases.json",
    "auth_password_file": ".review_web_password",
    "session_ttl_seconds": 28800,
    "organize_extra_args": [
      "--ollama-timeout",
      "1800",
      "--ollama-retries",
      "0"
    ]
  }
}
JSON
}

read_models_from_config() {
  "$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
p = Path("assistant_config.json")
if not p.exists():
    print("qwen2.5:7b-instruct")
    raise SystemExit(0)
try:
    cfg = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print("qwen2.5:7b-instruct")
    raise SystemExit(0)
service = cfg.get("service", {}) if isinstance(cfg, dict) else {}
model = str(service.get("model", "")).strip() if isinstance(service, dict) else ""
print(model or "qwen2.5:7b-instruct")
PY
}

while [[ $# -gt 0 ]]; do
  arg="$1"
  case "$arg" in
    --help)
      print_usage
      exit 0
      ;;
    --full-setup)
      INSTALL_SYSTEM_DEPS=1
      INSTALL_OLLAMA=1
      PULL_MODELS=1
      ;;
    --install-system-deps)
      INSTALL_SYSTEM_DEPS=1
      ;;
    --install-ollama)
      INSTALL_OLLAMA=1
      ;;
    --pull-models)
      PULL_MODELS=1
      ;;
    --model)
      shift
      if [[ $# -eq 0 ]]; then
        echo "[ERROR] --model requires a value" >&2
        exit 2
      fi
      MODEL_OVERRIDE="$1"
      ;;
    --no-systemd)
      INSTALL_SYSTEMD=0
      ;;
    --no-start)
      START_SERVICE=0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
  shift
done

echo "[0/7] Preflight"
if ! cmd_exists "$PYTHON_BIN"; then
  echo "[ERROR] Python interpreter not found: $PYTHON_BIN" >&2
  exit 2
fi

if [[ "$INSTALL_SYSTEM_DEPS" -eq 1 ]]; then
  if ! cmd_exists apt-get; then
    echo "[ERROR] --install-system-deps requires apt-get (Debian/Ubuntu)." >&2
    exit 2
  fi
fi

if [[ "$INSTALL_SYSTEM_DEPS" -eq 1 ]]; then
  echo "[1/7] Installing system dependencies"
  run_as_root apt-get update
  run_as_root apt-get install -y curl python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-deu poppler-utils
else
  echo "[1/7] Skipping system dependencies (use --install-system-deps or --full-setup)"
fi

if [[ "$INSTALL_OLLAMA" -eq 1 ]]; then
  echo "[2/7] Installing/starting Ollama"
  if ! cmd_exists curl; then
    echo "[ERROR] curl is required to install Ollama" >&2
    exit 2
  fi
  if ! cmd_exists ollama; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    echo "Ollama already installed: $(command -v ollama)"
  fi

  if cmd_exists systemctl; then
    run_as_root systemctl enable ollama || true
    run_as_root systemctl start ollama || true
  fi
else
  echo "[2/7] Skipping Ollama installation (use --install-ollama or --full-setup)"
fi

echo "[3/7] Preparing Python virtual environment"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "[4/7] Ensuring required folders/files"
mkdir -p "$PROJECT_DIR/inbox"
ensure_assistant_config

echo "[5/7] Ensuring web password file"
if [[ ! -f "$PROJECT_DIR/.review_web_password" ]]; then
  "$VENV_DIR/bin/python" - <<'PY' > "$PROJECT_DIR/.review_web_password"
import secrets
print(secrets.token_urlsafe(24))
PY
  chmod 600 "$PROJECT_DIR/.review_web_password"
  echo "Generated new password file at $PROJECT_DIR/.review_web_password"
else
  chmod 600 "$PROJECT_DIR/.review_web_password"
fi

if [[ "$PULL_MODELS" -eq 1 ]]; then
  echo "[6/7] Pulling Ollama model(s)"
  if ! cmd_exists ollama; then
    echo "[ERROR] ollama not found. Use --install-ollama or install manually first." >&2
    exit 2
  fi

  MODELS_RAW="$MODEL_OVERRIDE"
  if [[ -z "$MODELS_RAW" ]]; then
    MODELS_RAW="$(cd "$PROJECT_DIR" && read_models_from_config)"
  fi

  if [[ -z "$MODELS_RAW" ]]; then
    MODELS_RAW="qwen2.5:7b-instruct"
  fi

  IFS=',' read -r -a MODELS <<< "$MODELS_RAW"
  for model in "${MODELS[@]}"; do
    model="$(echo "$model" | xargs)"
    [[ -z "$model" ]] && continue
    echo "Pulling model: $model"
    ollama pull "$model"
  done

  echo "Checking Ollama API availability"
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; then
    echo "[ERROR] Ollama API not reachable on 127.0.0.1:11434" >&2
    exit 2
  fi
else
  echo "[6/7] Skipping model pull (use --pull-models or --full-setup)"
fi

echo "[7/7] Basic sanity checks"
"$VENV_DIR/bin/python" -m py_compile "$PROJECT_DIR/organize.py" "$PROJECT_DIR/review_web.py" "$PROJECT_DIR/doc_assistant_service.py"

echo "[post] Installing systemd user unit (optional)"
if [[ "$INSTALL_SYSTEMD" -eq 1 ]]; then
  mkdir -p "$HOME/.config/systemd/user"
  cp "$PROJECT_DIR/systemd/ollama-document-assistant.service" "$HOME/.config/systemd/user/ollama-document-assistant.service"
  systemctl --user daemon-reload
  systemctl --user enable ollama-document-assistant.service

  if [[ "$START_SERVICE" -eq 1 ]]; then
    systemctl --user restart ollama-document-assistant.service
  fi
fi

echo "[done] Installation finished"
echo "Project dir: $PROJECT_DIR"
echo "Config file: $PROJECT_DIR/assistant_config.json"
echo "Password file: $PROJECT_DIR/.review_web_password"
echo "Review URL: http://127.0.0.1:8765"

echo "Current web password:"
head -n 1 "$PROJECT_DIR/.review_web_password"
