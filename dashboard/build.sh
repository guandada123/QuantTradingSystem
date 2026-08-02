#!/usr/bin/env bash
# =========================================================
# QTS Dashboard — Build script for production dist
# Usage: cd dashboard && bash build.sh
# =========================================================
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DIST="$SRC/dist"

# ---------------------------------------------------------
# 构建工具解析：禁止硬编码本机绝对路径（会在 CI runner 上 exit 127，
# 且把本地用户名泄漏进仓库）。优先取 PATH，缺失时回退 npx 按需拉取。
# DO NOT REVERT to absolute paths.
# ---------------------------------------------------------
resolve_tool() {
    local bin="$1" pkg="$2"
    if command -v "$bin" >/dev/null 2>&1; then
        echo "$bin"
    elif command -v npx >/dev/null 2>&1; then
        echo "npx --yes $pkg"
    else
        echo "❌ 未找到 $bin，且 npx 不可用。请先执行: npm install -g $pkg" >&2
        exit 127
    fi
}

CSSO="$(resolve_tool csso csso-cli)"
TERSER="$(resolve_tool terser terser)"

echo "🔧 QTS Dashboard Build — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "   csso   : $CSSO"
echo "   terser : $TERSER"

# 1. Ensure dist directory exists
mkdir -p "$DIST"

# 2. Minify CSS
echo "  → Minifying style.css …"
$CSSO "$SRC/style.css" --output "$DIST/style.css"

# 3. Minify JS
echo "  → Minifying app.js …"
$TERSER "$SRC/app.js" --compress --mangle --output "$DIST/app.js"

# 3.5 补齐末尾换行 —— csso/terser 输出不带 EOF newline，而 pre-commit 的
# end-of-file-fixer 会在提交时补上，导致 CI build-check 重建后必然 diff、
# 且 `git diff --ignore-all-space` 并不能忽略「缺失末尾换行」。
# 不补齐 = build-check 永远红。DO NOT REMOVE.
for _f in "$DIST/style.css" "$DIST/app.js"; do
    [ -n "$(tail -c 1 "$_f")" ] && printf '\n' >> "$_f"
done

# 4. Copy static files (HTML, SVG, manifest, service worker, design tokens)
echo "  → Copying static assets …"
cp "$SRC/index.html"        "$DIST/index.html"
cp "$SRC/favicon.svg"       "$DIST/favicon.svg"
cp "$SRC/manifest.json"     "$DIST/manifest.json"
cp "$SRC/sw.js"             "$DIST/sw.js"
cp "$SRC/design-tokens.css" "$DIST/design-tokens.css"

# 5. Copy deployment files
echo "  → Copying deployment config …"
cp "$SRC/Dockerfile"        "$DIST/Dockerfile"
cp "$SRC/nginx.conf"        "$DIST/nginx.conf"

# 6. Generate build.json
COMMIT_HASH="$(cd "$SRC" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$DIST/build.json" <<EOF
{
  "version": "${BUILT_AT}-${COMMIT_HASH}",
  "built_at": "${BUILT_AT}",
  "mode": "prod",
  "files": [
    "app.js",
    "app.spa.js",
    "build.json",
    "design-tokens.css",
    "favicon.svg",
    "index.html",
    "manifest.json",
    "style.css",
    "sw.js"
  ]
}
EOF

echo "✅ Build complete → $DIST"
echo "   Version: ${BUILT_AT}-${COMMIT_HASH}"
