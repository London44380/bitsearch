#!/usr/bin/env bash
# BitSearch installer / uninstaller (no root needed).
#   ./install.sh              install to ~/.local/bin
#   ./install.sh --prefix DIR install to DIR/bin
#   ./install.sh --uninstall  remove the command (your config is kept)
set -euo pipefail

PREFIX="${HOME}/.local"
ACTION="install"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

BIN_DIR="${PREFIX}/bin"
TARGET="${BIN_DIR}/bitsearch"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bitsearch.py"

if [ "$ACTION" = "uninstall" ]; then
  rm -f -- "$TARGET"
  echo "Removed ${TARGET} (config in ~/.config/bitsearch was left untouched)."
  exit 0
fi

command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' \
  || { echo "Python 3.8 or newer is required." >&2; exit 1; }
[ -f "$SRC" ] || { echo "bitsearch.py not found next to install.sh." >&2; exit 1; }

mkdir -p -- "$BIN_DIR"
install -m 755 -- "$SRC" "$TARGET"
echo "Installed: ${TARGET}"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) echo "Note: ${BIN_DIR} is not in your PATH. Add this to your shell profile:"
     echo "  export PATH=\"${BIN_DIR}:\$PATH\"" ;;
esac

echo
echo "Try it:   bitsearch ubuntu --public"
echo "Private trackers (optional): bitsearch --init-config  (see README)"
