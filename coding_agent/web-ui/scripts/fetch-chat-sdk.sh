#!/usr/bin/env bash
# Build @sarchauhan/chat from source at a pinned chat-sdk commit.
# The package lives at packages/chat in an npm-workspaces monorepo and
# 0.1.0 is not on npm, so we build it from git and stage only package.json
# + dist into .chat-sdk/chat, which package.json references as a file: dep.
set -euo pipefail
SHA=e1d3f3c1109ff39476bc24fae5303e3e540e479b
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HERE/.chat-sdk"
SRC="$OUT/src"
if [ -f "$OUT/chat/.sha" ] && [ "$(cat "$OUT/chat/.sha")" = "$SHA" ]; then exit 0; fi
rm -rf "$OUT"
mkdir -p "$SRC"
git -C "$SRC" init -q
git -C "$SRC" fetch -q --depth 1 https://github.com/Sarthakischauhan/chat-sdk.git "$SHA"
git -C "$SRC" checkout -q FETCH_HEAD
(cd "$SRC" && npm ci --no-audit --no-fund && npm run build:chat)
mkdir -p "$OUT/chat"
cp "$SRC/packages/chat/package.json" "$OUT/chat/"
cp -R "$SRC/packages/chat/dist" "$OUT/chat/dist"
echo "$SHA" > "$OUT/chat/.sha"
rm -rf "$SRC"
