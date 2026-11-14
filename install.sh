#!/usr/bin/env bash
# DroidTrace installer: builds the sandbox image (QEMU + plugin + CLI) and installs
# a `droidtrace` command that runs it. Requires Docker.
#   curl -fsSL https://raw.githubusercontent.com/satpath-lab/droidtrace/main/install.sh | bash
set -euo pipefail
REPO_URL="${DROIDTRACE_REPO:-https://github.com/satpath-lab/droidtrace.git}"
BIN_DIR="${DROIDTRACE_BIN:-$HOME/.local/bin}"
HOME_DIR="${DROIDTRACE_HOME:-$HOME/.droidtrace}"

command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/get-docker/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start it and retry."; exit 1; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ ! -f "$SRC/docker/Dockerfile" ]; then
  SRC="$HOME_DIR/src"
  if [ -d "$SRC/.git" ]; then git -C "$SRC" pull -q; else git clone -q --depth 1 "$REPO_URL" "$SRC"; fi
fi

echo "==> Building sandbox image (first build compiles QEMU, ~10 min)"
docker build -t droidtrace:local -f "$SRC/docker/Dockerfile" "$SRC"

mkdir -p "$BIN_DIR" "$HOME_DIR/images/arm64"
cat > "$BIN_DIR/droidtrace" <<'WRAP'
#!/usr/bin/env bash
# Runs DroidTrace in its sandbox container. The current directory is mounted at /work.
HOME_DIR="${DROIDTRACE_HOME:-$HOME/.droidtrace}"
PORT="${DROIDTRACE_PORT:-8765}"
TTY=""; [ -t 0 ] && TTY="-it"
EXTRA=()
case "${1:-}" in
  run|view)
    EXTRA=(--host 0.0.0.0 --no-browser)
    ( sleep 3; command -v open >/dev/null && open "http://127.0.0.1:$PORT/" \
        || xdg-open "http://127.0.0.1:$PORT/" ) >/dev/null 2>&1 & ;;
esac
exec docker run --rm $TTY --init \
  --cap-drop ALL --security-opt no-new-privileges \
  -p "127.0.0.1:$PORT:8765" \
  -v "$PWD:/work" -v "$HOME_DIR:/home/analyst/.droidtrace" \
  droidtrace:local "$@" "${EXTRA[@]}"
WRAP
chmod +x "$BIN_DIR/droidtrace"

echo "==> Installed: $BIN_DIR/droidtrace"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "    Add to PATH: export PATH=\"$BIN_DIR:\$PATH\"";; esac
echo
echo "Next:"
echo "  1. Put an Android arm64 QEMU image in $HOME_DIR/images/arm64/ (see docs/operations.md)"
echo "  2. droidtrace doctor"
echo "  3. droidtrace run app.apk        # opens the live trace in your browser"
