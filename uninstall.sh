#!/usr/bin/env bash
# Remove yarasort. Mirrors install.sh:  sudo ./uninstall.sh   or   ./uninstall.sh --user
# Config files and your move history are kept unless you pass --purge.
set -euo pipefail

MODE=system
PREFIX=""
PURGE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --user)   MODE=user ;;
        --prefix) PREFIX="${2:?--prefix needs a directory}"; shift ;;
        --purge)  PURGE=1 ;;
        -h|--help) echo "Usage: $0 [--user] [--prefix DIR] [--purge]"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

if [ "$MODE" = system ]; then
    [ "$(id -u)" -eq 0 ] || { echo "uninstall.sh: run with sudo, or pass --user." >&2; exit 1; }
    PREFIX="${PREFIX:-/usr/local}"
    CONFIG_DIR="/etc/yarasort"
    UNIT="/etc/systemd/user/yarasort-watch.service"
else
    PREFIX="${PREFIX:-$HOME/.local}"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/yarasort"
    UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/yarasort-watch.service"
fi

if [ "$MODE" = user ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now yarasort-watch 2>/dev/null || true
fi

rm -f "$PREFIX/bin/yarasort" "$UNIT"
rm -rf "$PREFIX/lib/yarasort"
echo "Removed program files from $PREFIX."

if [ "$PURGE" -eq 1 ]; then
    rm -rf "$CONFIG_DIR"
    echo "Removed $CONFIG_DIR."
else
    echo "Kept config ($CONFIG_DIR) and move history (~/.local/state/yarasort). Use --purge to remove config."
fi
echo "If you enabled the watch service as another user, run: systemctl --user disable --now yarasort-watch"
