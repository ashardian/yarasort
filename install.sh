#!/usr/bin/env bash
# yarasort installer.
#   sudo ./install.sh            system-wide (/usr/local, config in /etc/yarasort)
#   ./install.sh --user          for the current user only (~/.local, ~/.config)
# Needs: python3 (>= 3.9) with the venv module, and internet access for pip.
set -euo pipefail

MODE=system
PREFIX=""
PY="${PYTHON:-python3}"

usage() {
    cat <<USAGE
Usage: $0 [--user] [--prefix DIR] [--python PYTHON]

  --user           install for the current user (no root needed)
  --prefix DIR     install prefix (default: /usr/local, or ~/.local with --user)
  --python PYTHON  interpreter to use (default: python3)
USAGE
}

die()  { echo "install.sh: error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --user)   MODE=user ;;
        --prefix) PREFIX="${2:?--prefix needs a directory}"; shift ;;
        --python) PY="${2:?--python needs an interpreter}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown option: $1" ;;
    esac
    shift
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$MODE" = system ]; then
    [ "$(id -u)" -eq 0 ] || die "system-wide install needs root. Use sudo, or pass --user."
    PREFIX="${PREFIX:-/usr/local}"
    CONFIG_DIR="/etc/yarasort"
    UNIT_DIR="/etc/systemd/user"
else
    PREFIX="${PREFIX:-$HOME/.local}"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/yarasort"
    UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
fi
LIB_DIR="$PREFIX/lib/yarasort"
VENV="$LIB_DIR/venv"
BIN="$PREFIX/bin/yarasort"

command -v "$PY" >/dev/null 2>&1 || die "$PY not found. Install it: sudo apt install python3"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python 3.9 or newer is required."

info "Creating virtual environment in $VENV"
mkdir -p "$LIB_DIR"
rm -rf "$VENV"
"$PY" -m venv "$VENV" || die "could not create a venv. Install it: sudo apt install python3-venv"

info "Installing yarasort and its dependencies (yara-python)"
if ! "$VENV/bin/pip" install --quiet "$SRC"; then
    echo "pip could not install everything (offline, or yara-python failed to build)." >&2
    echo "Falling back to the distribution's python3-yara package." >&2
    rm -rf "$VENV"
    "$PY" -m venv --system-site-packages "$VENV"
    "$VENV/bin/python" -c 'import yara' 2>/dev/null \
        || die "install it first:  sudo apt install python3-yara   then re-run this script."
    if ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        "$VENV/bin/python" -c 'import tomli' 2>/dev/null \
            || die "Python < 3.11 also needs:  sudo apt install python3-tomli   then re-run."
    fi
    "$VENV/bin/pip" install --quiet --no-deps "$SRC" || die "pip install failed."
fi

info "Linking $BIN"
mkdir -p "$PREFIX/bin"
ln -sf "$VENV/bin/yarasort" "$BIN"

if [ ! -e "$CONFIG_DIR/config.toml" ]; then
    info "Writing default config to $CONFIG_DIR/config.toml"
    mkdir -p "$CONFIG_DIR"
    "$VENV/bin/yarasort" config --print-default > "$CONFIG_DIR/config.toml"
else
    info "Keeping existing config: $CONFIG_DIR/config.toml"
fi

info "Installing systemd user unit to $UNIT_DIR (not enabled)"
mkdir -p "$UNIT_DIR"
sed "s|@BIN@|$BIN|" "$SRC/systemd/yarasort-watch.service" > "$UNIT_DIR/yarasort-watch.service"

info "Running self-check"
"$VENV/bin/yarasort" doctor || echo "Self-check reported problems (see above)." >&2

cat <<DONE

Installed: $BIN
Try it:
    yarasort scan ~/Downloads             # what is in there?
    yarasort sort ~/Downloads             # preview
    yarasort sort ~/Downloads --apply     # do it (undo with: yarasort undo --apply)

Keep ~/Downloads sorted automatically (each user runs this once):
    systemctl --user daemon-reload
    systemctl --user enable --now yarasort-watch
    journalctl --user -u yarasort-watch -f

Edit the watched folders and categories in: $CONFIG_DIR/config.toml
DONE
