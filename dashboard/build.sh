#!/usr/bin/env bash
# =========================================================
# QTS Dashboard — Build script for production dist
# Usage: cd dashboard && bash build.sh
# =========================================================
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DIST="$SRC/dist"

echo "🔧 QTS Dashboard Build — $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1. Ensure dist directory exists
mkdir -p "$DIST"

# 2. Minify CSS
echo "  → Minifying style.css …"
/Users/guan/.workbuddy/binaries/node/versions/22.22.2/bin/csso \
    "$SRC/style.css" \
    --output "$DIST/style.css" 2>/dev/null

# 3. Minify JS
echo "  → Minifying app.js …"
/Users/guan/.workbuddy/binaries/node/versions/22.22.2/bin/terser \
    "$SRC/app.js" \
    --compress --mangle \
    --output "$DIST/app.js" 2>/dev/null

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
