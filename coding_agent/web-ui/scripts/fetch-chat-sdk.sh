#!/usr/bin/env bash
# Build @sarchauhan/chat and the @sarchauhan/protocol and @sarchauhan/adapter
# packages it imports from source at one pinned chat-sdk commit. They live in
# an npm-workspaces monorepo (packages/*) and these builds are not on npm, so
# we build them from git and stage only each package.json + dist into
# .chat-sdk/<name>, which package.json references as file: deps.
set -euo pipefail
SHA=eb79fcf1979e06fa6a4312fe0e212ea53ba5c05f
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HERE/.chat-sdk"
SRC="$OUT/src"
if [ -f "$OUT/.sha" ] && [ "$(cat "$OUT/.sha")" = "$SHA" ]; then exit 0; fi
rm -rf "$OUT"
mkdir -p "$SRC"
git -C "$SRC" init -q
git -C "$SRC" fetch -q --depth 1 https://github.com/Sarthakischauhan/chat-sdk.git "$SHA"
git -C "$SRC" checkout -q FETCH_HEAD
(cd "$SRC" && npm ci --no-audit --no-fund && npm run build:chat)
for name in chat protocol adapter; do
  mkdir -p "$OUT/$name"
  cp "$SRC/packages/$name/package.json" "$OUT/$name/"
  cp -R "$SRC/packages/$name/dist" "$OUT/$name/dist"
done
# In the monorepo, chat and adapter depend on their sibling packages by
# version, which npm would fetch as older registry builds. Point those deps at
# the staged siblings so the whole tree runs this one commit.
node -e '
const fs = require("fs");
for (const name of ["chat", "protocol", "adapter"]) {
  const file = process.argv[1] + "/" + name + "/package.json";
  const pkg = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const dep of Object.keys(pkg.dependencies ?? {})) {
    const sibling = dep.replace("@sarchauhan/", "");
    if (dep.startsWith("@sarchauhan/") && fs.existsSync(process.argv[1] + "/" + sibling)) {
      pkg.dependencies[dep] = "file:../" + sibling;
    }
  }
  fs.writeFileSync(file, JSON.stringify(pkg, null, 2) + "\n");
}' "$OUT"
echo "$SHA" > "$OUT/.sha"
rm -rf "$SRC"
