#!/usr/bin/env bash
set -euo pipefail

DEFAULT_INSTALL_DIR="$HOME/.local/share/joda"
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
UNIT_PATH="$HOME/.config/systemd/user/joda.service"
REMOVE_MODELS=0
REMOVE_OLLAMA=0
ASSUME_YES=0

print_usage() {
  cat <<'USAGE'
Usage: bash ./uninstall.sh [options]

Options:
  --install-dir <dir>   Installation directory to remove
                        (default: ~/.local/share/joda)
  --remove-models       Remove Ollama models used by this project (qwen2.5:7b-instruct)
  --remove-ollama       Try to uninstall Ollama service/package as well (Debian/Ubuntu)
  --yes                 Skip confirmation prompt
  --help                Show this help

Examples:
  bash ./uninstall.sh
  bash ./uninstall.sh --install-dir ~/.local/share/joda --remove-models
USAGE
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return
  fi
  if cmd_exists sudo; then
    sudo "$@"
    return
  fi
  echo "[WARN] Root privileges required for: $* (sudo not found)"
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)
      print_usage
      exit 0
      ;;
    --install-dir)
      shift
      if [[ $# -eq 0 ]]; then
        echo "[ERROR] --install-dir requires a value" >&2
        exit 2
      fi
      INSTALL_DIR="$1"
      ;;
    --remove-models)
      REMOVE_MODELS=1
      ;;
    --remove-ollama)
      REMOVE_OLLAMA=1
      ;;
    --yes)
      ASSUME_YES=1
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"
if [[ "$INSTALL_DIR" != /* ]]; then
  INSTALL_DIR="$PWD/$INSTALL_DIR"
fi
INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

echo "Will uninstall joda"
echo "- install dir: $INSTALL_DIR"
echo "- unit file: $UNIT_PATH"
if [[ "$REMOVE_MODELS" -eq 1 ]]; then
  echo "- remove models: yes"
fi
if [[ "$REMOVE_OLLAMA" -eq 1 ]]; then
  echo "- remove ollama: yes"
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  read -r -p "Continue? [y/N] " ans
  case "${ans,,}" in
    y|yes) ;;
    *)
      echo "Aborted."
      exit 0
      ;;
  esac
fi

if cmd_exists systemctl; then
  echo "[1/5] Stopping and disabling user service"
  systemctl --user stop joda.service >/dev/null 2>&1 || true
  systemctl --user disable joda.service >/dev/null 2>&1 || true
fi

if [[ -f "$UNIT_PATH" ]]; then
  echo "[2/5] Removing user unit"
  rm -f "$UNIT_PATH"
  if cmd_exists systemctl; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user reset-failed >/dev/null 2>&1 || true
  fi
else
  echo "[2/5] User unit not present, skipping"
fi

if [[ -d "$INSTALL_DIR" ]]; then
  echo "[3/5] Removing install directory"
  rm -rf "$INSTALL_DIR"
else
  echo "[3/5] Install directory not present, skipping"
fi

if [[ "$REMOVE_MODELS" -eq 1 ]]; then
  echo "[4/5] Removing model(s)"
  if cmd_exists ollama; then
    ollama rm qwen2.5:7b-instruct >/dev/null 2>&1 || true
  else
    echo "[WARN] ollama command not found, cannot remove models"
  fi
else
  echo "[4/5] Keeping Ollama models"
fi

if [[ "$REMOVE_OLLAMA" -eq 1 ]]; then
  echo "[5/5] Trying to uninstall Ollama"
  if cmd_exists systemctl; then
    run_as_root systemctl stop ollama >/dev/null 2>&1 || true
    run_as_root systemctl disable ollama >/dev/null 2>&1 || true
  fi
  if cmd_exists apt-get; then
    run_as_root apt-get remove -y ollama >/dev/null 2>&1 || true
    run_as_root apt-get autoremove -y >/dev/null 2>&1 || true
  else
    echo "[WARN] apt-get not available; remove Ollama manually for this OS"
  fi
else
  echo "[5/5] Keeping Ollama installation"
fi

echo "Done."
