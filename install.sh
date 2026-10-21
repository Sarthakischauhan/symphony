#!/bin/sh
# Symphony installer.
#   curl -fsSL https://raw.githubusercontent.com/Sarthakischauhan/symphony/main/install.sh | sh
#
# Installs the `symphony` command (PyPI package `symphony-code`) as a uv tool,
# pinned to the latest GitHub release, then the matching Symphony Web assets
# (release asset web-<version>.tar.gz, checked against its .sha256) into
# ~/.symphony/web/<version>, switched in via the ~/.symphony/web/current
# symlink. Re-running upgrades.
#
# Environment:
#   SYMPHONY_VERSION  release to install, e.g. 0.0.1 or v0.0.1 (default: latest release)
# Options:
#   --uninstall       remove the Symphony uv tool
#   -h, --help        show this help
#
# All logic lives in main(), invoked on the last line, so a partially
# downloaded script never runs.

set -eu

REPO="Sarthakischauhan/symphony"
PACKAGE="symphony-code"
COMMAND="symphony"

say() { printf '%s\n' "symphony-install: $*"; }
err() {
    printf '%s\n' "symphony-install: error: $1" >&2
    if [ "${2:-}" != "" ]; then
        printf '%s\n' "symphony-install: hint: $2" >&2
    fi
    exit 1
}
has() { command -v "$1" >/dev/null 2>&1; }

usage() {
    cat <<USAGE
Symphony installer

Usage: sh install.sh [--uninstall] [--help]

Environment:
  SYMPHONY_VERSION  release to install (e.g. 0.0.1); default: latest GitHub release
USAGE
}

detect_platform() {
    os=$(uname -s 2>/dev/null || echo unknown)
    arch=$(uname -m 2>/dev/null || echo unknown)
    case "$os" in
        Linux) os=linux ;;
        Darwin) os=macos ;;
        MINGW* | MSYS* | CYGWIN* | Windows_NT)
            err "Windows is not supported by this installer ($os)." \
                "Use WSL, or install manually: uv tool install $PACKAGE" ;;
        *) err "unsupported operating system: $os" "Symphony's installer supports macOS and Linux." ;;
    esac
    case "$arch" in
        x86_64 | amd64) arch=x86_64 ;;
        arm64 | aarch64) arch=arm64 ;;
        *) err "unsupported architecture: $arch" "Supported: x86_64, arm64/aarch64." ;;
    esac
    say "platform: $os/$arch"
}

find_uv() {
    if has uv; then
        UV=$(command -v uv)
        return 0
    fi
    for candidate in "${XDG_BIN_HOME:-}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            UV=$candidate
            return 0
        fi
    done
    return 1
}

ensure_uv() {
    if find_uv; then
        say "using uv: $UV"
        return 0
    fi
    has curl || err "curl is required to install uv." "Install curl with your package manager, then re-run."
    say "uv not found; installing it with astral's official installer"
    curl -LsSf https://astral.sh/uv/install.sh | sh ||
        err "uv installation failed." "See https://docs.astral.sh/uv/getting-started/installation/ and re-run this script."
    find_uv || err "uv was installed but could not be found in ~/.local/bin or ~/.cargo/bin." \
        "Open a new shell (or add uv's directory to PATH) and re-run."
    say "using uv: $UV"
}

resolve_version() {
    version=${SYMPHONY_VERSION:-}
    if [ -z "$version" ]; then
        has curl || err "curl is required to look up the latest release." "Set SYMPHONY_VERSION=<version> to skip the lookup."
        say "looking up the latest release of $REPO"
        json=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null) ||
            err "could not find a published GitHub release for $REPO." \
                "Check https://github.com/$REPO/releases, or set SYMPHONY_VERSION=<version>."
        version=$(printf '%s\n' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
        [ -n "$version" ] || err "could not parse the latest release tag from the GitHub API." \
            "Set SYMPHONY_VERSION=<version> and re-run."
    fi
    version=${version#v}
    say "version: $version"
}

check_path() {
    bindir=$("$UV" tool dir --bin 2>/dev/null) || bindir="$HOME/.local/bin"
    case ":$PATH:" in
        *":$bindir:"*)
            say "'$COMMAND' is on your PATH ($bindir)"
            return 0 ;;
    esac
    say "'$COMMAND' was installed to $bindir, which is not on your PATH."
    shell_name=$(basename "${SHELL:-sh}")
    case "$shell_name" in
        zsh) rc="$HOME/.zshrc"; line="export PATH=\"$bindir:\$PATH\"" ;;
        bash) rc="$HOME/.bashrc"; line="export PATH=\"$bindir:\$PATH\"" ;;
        fish) rc="$HOME/.config/fish/config.fish"; line="fish_add_path \"$bindir\"" ;;
        *) rc="$HOME/.profile"; line="export PATH=\"$bindir:\$PATH\"" ;;
    esac
    say "add this line to $rc, then open a new shell:"
    printf '\n    %s\n\n' "$line"
}

do_install() {
    detect_platform
    ensure_uv
    resolve_version
    say "installing $PACKAGE==$version as a uv tool (re-running upgrades)"
    "$UV" tool install --force --python ">=3.11" "$PACKAGE==$version" ||
        err "uv tool install $PACKAGE==$version failed." \
            "Check that version $version exists on PyPI (https://pypi.org/project/$PACKAGE/) and your network is up."
    install_web
    check_path
    say "done. Run '$COMMAND --version' to verify."
}

install_web() {
    # The installed CLI does the download, checksum, extract and atomic switch,
    # so install.sh and `symphony web --update` share one implementation.
    bindir=$("$UV" tool dir --bin 2>/dev/null) || bindir="$HOME/.local/bin"
    say "installing Symphony Web $version assets"
    # Not fatal: the terminal UI works without them, and a release published
    # before web assets existed has none. The previous assets stay active.
    if ! "$bindir/$COMMAND" web --update --bundle-version "$version"; then
        say "warning: Symphony Web $version assets were not installed; 'symphony web' needs them."
        say "hint: check https://github.com/$REPO/releases/tag/v$version for web-$version.tar.gz, then run '$COMMAND web --update'."
    fi
}

do_uninstall() {
    find_uv || err "uv not found, so there is nothing to uninstall via uv." "If uv lives elsewhere, add it to PATH and re-run."
    if "$UV" tool list 2>/dev/null | grep -q "^$PACKAGE "; then
        "$UV" tool uninstall "$PACKAGE" || err "uv tool uninstall $PACKAGE failed." "Try running it manually: uv tool uninstall $PACKAGE"
        say "uninstalled $PACKAGE"
    else
        say "$PACKAGE is not installed as a uv tool; nothing to do"
    fi
}

main() {
    action=install
    for arg in "$@"; do
        case "$arg" in
            --uninstall) action=uninstall ;;
            -h | --help) usage; exit 0 ;;
            *) err "unknown option: $arg" "Run with --help for usage." ;;
        esac
    done
    if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
        say "warning: running as root; Symphony installs per user and never needs sudo"
    fi
    case "$action" in
        install) do_install ;;
        uninstall) do_uninstall ;;
    esac
}

main "$@"
