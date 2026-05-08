#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_SYSTEMD=1
START_SERVICE=1

for arg in "$@"; do
  case "$arg" in
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
done

echo "[1/6] Preparing Python virtual environment"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "[2/6] Ensuring required folders/files"
mkdir -p "$PROJECT_DIR/inbox"

if [[ ! -f "$PROJECT_DIR/assistant_config.json" ]]; then
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
fi

echo "[3/6] Ensuring web password file"
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

echo "[4/6] Basic sanity checks"
"$VENV_DIR/bin/python" -m py_compile "$PROJECT_DIR/organize.py" "$PROJECT_DIR/review_web.py" "$PROJECT_DIR/doc_assistant_service.py"

echo "[5/6] Installing systemd user unit (optional)"
if [[ "$INSTALL_SYSTEMD" -eq 1 ]]; then
  mkdir -p "$HOME/.config/systemd/user"
  cp "$PROJECT_DIR/systemd/ollama-document-assistant.service" "$HOME/.config/systemd/user/ollama-document-assistant.service"
  systemctl --user daemon-reload
  systemctl --user enable ollama-document-assistant.service

  if [[ "$START_SERVICE" -eq 1 ]]; then
    systemctl --user restart ollama-document-assistant.service
  fi
fi

echo "[6/6] Done"
echo "Project dir: $PROJECT_DIR"
echo "Config file: $PROJECT_DIR/assistant_config.json"
echo "Password file: $PROJECT_DIR/.review_web_password"
echo "Review URL: http://127.0.0.1:8765"

echo "Current web password:"
head -n 1 "$PROJECT_DIR/.review_web_password"
