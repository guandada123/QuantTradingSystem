#!/bin/bash
# ============================================================
# Dashboard Build Script v1.0
# 用法: ./build.sh              → 构建到 dist/
#       ./build.sh --dev        → 开发模式（不压缩）
#       ./build.sh --watch      → 监听模式
# ============================================================
set +e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"

DEV_MODE=false
WATCH_MODE=false

for arg in "$@"; do
    case "$arg" in
        --dev)   DEV_MODE=true ;;
        --watch) WATCH_MODE=true ;;
    esac
done

# 清理 + 创建输出目录
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "=== Dashboard Build ==="
echo "Source: $SCRIPT_DIR"
echo "Output: $DIST_DIR"
echo "Mode:   $( $DEV_MODE && echo 'dev' || echo 'prod' )"
echo ""

# ---------- 1. 复制静态资源 ----------
cp -v "$SCRIPT_DIR"/*.html "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/*.svg "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/manifest.json "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/nginx.conf "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/Dockerfile "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/bt_report_data.json "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/design-tokens.css "$DIST_DIR/" 2>/dev/null
cp -v "$SCRIPT_DIR"/sw.js "$DIST_DIR/" 2>/dev/null

# ---------- 2. CSS 压缩 ----------
if ! $DEV_MODE; then
    if command -v csso &>/dev/null; then
        echo "--- CSS 压缩 (csso) ---"
        csso "$SCRIPT_DIR/style.css" --output "$DIST_DIR/style.css"
        echo "  style.css: $(wc -c < "$SCRIPT_DIR/style.css" | tr -d ' ') → $(wc -c < "$DIST_DIR/style.css" | tr -d ' ') bytes"
    elif command -v npx &>/dev/null && npx --yes csso-cli --version &>/dev/null 2>&1; then
        echo "--- CSS 压缩 (npx csso) ---"
        npx --yes csso-cli "$SCRIPT_DIR/style.css" --output "$DIST_DIR/style.css"
    else
        echo "--- CSS: csso 不可用，使用原文件 ---"
        cp "$SCRIPT_DIR/style.css" "$DIST_DIR/"
    fi
else
    cp "$SCRIPT_DIR/style.css" "$DIST_DIR/"
fi

# ---------- 3. JS 压缩 ----------
if ! $DEV_MODE; then
    if command -v terser &>/dev/null; then
        echo "--- JS 压缩 (terser) ---"
        terser "$SCRIPT_DIR/app.js" --compress --mangle --output "$DIST_DIR/app.js"
        echo "  app.js: $(wc -c < "$SCRIPT_DIR/app.js" | tr -d ' ') → $(wc -c < "$DIST_DIR/app.js" | tr -d ' ') bytes"
        if [ -f "$SCRIPT_DIR/app.spa.js" ]; then
            terser "$SCRIPT_DIR/app.spa.js" --compress --mangle --output "$DIST_DIR/app.spa.js"
            echo "  app.spa.js: $(wc -c < "$SCRIPT_DIR/app.spa.js" | tr -d ' ') → $(wc -c < "$DIST_DIR/app.spa.js" | tr -d ' ') bytes"
        fi
    elif command -v npx &>/dev/null; then
        echo "--- JS 压缩 (npx terser) ---"
        npx --yes terser "$SCRIPT_DIR/app.js" --compress --mangle --output "$DIST_DIR/app.js"
        if [ -f "$SCRIPT_DIR/app.spa.js" ]; then
            npx --yes terser "$SCRIPT_DIR/app.spa.js" --compress --mangle --output "$DIST_DIR/app.spa.js"
        fi
    else
        echo "--- JS: terser 不可用，使用原文件 ---"
        cp "$SCRIPT_DIR/app.js" "$DIST_DIR/"
        [ -f "$SCRIPT_DIR/app.spa.js" ] && cp "$SCRIPT_DIR/app.spa.js" "$DIST_DIR/"
    fi
else
    cp "$SCRIPT_DIR/app.js" "$DIST_DIR/"
    [ -f "$SCRIPT_DIR/app.spa.js" ] && cp "$SCRIPT_DIR/app.spa.js" "$DIST_DIR/"
fi

# ---------- 4. HTML 压缩 ----------
if ! $DEV_MODE; then
    if command -v html-minifier-terser &>/dev/null; then
        echo "--- HTML 压缩 (html-minifier-terser) ---"
        # 安全模式：不启用 --minify-js（会重命名 Vue 组件导致路由断裂）
        # 详见 conversation 记录 2026-06-13
        html-minifier-terser \
            --collapse-whitespace \
            --remove-comments \
            --remove-redundant-attributes \
            --remove-script-type-attributes \
            --remove-style-link-type-attributes \
            --use-short-doctype \
            "$DIST_DIR/index.html" \
            --output "$DIST_DIR/index.html" 2>/dev/null
        echo "  index.html: $(wc -c < "$SCRIPT_DIR/index.html" | tr -d ' ') → $(wc -c < "$DIST_DIR/index.html" | tr -d ' ') bytes"
    else
        echo "--- HTML: html-minifier-terser 不可用，使用原文件 ---"
    fi
    # 清理多余 MPA 页面（SPA 模式下仅保留 index.html）
    for f in "$DIST_DIR"/*.html; do
        [ "$f" = "$DIST_DIR/index.html" ] && continue
        rm -f "$f"
    done
fi

# ---------- 5. 生成版本清单 ----------
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BUILD_VERSION="${BUILD_TIME}-$(git rev-parse --short HEAD 2>/dev/null || echo 'dev')"

cat > "$DIST_DIR/build.json" <<JSON
{
  "version": "$BUILD_VERSION",
  "built_at": "$BUILD_TIME",
  "mode": "$($DEV_MODE && echo 'dev' || echo 'prod')",
  "files": $(cd "$DIST_DIR" && ls -1 *.html *.js *.css *.svg *.json 2>/dev/null | jq -R -s 'split("\n") | map(select(length > 0))')
}
JSON

echo "--- build.json ---"
cat "$DIST_DIR/build.json"

# ---------- 6. 统计 ----------
echo ""
echo "=== 构建完成 ==="
echo "输出目录: $DIST_DIR"
echo "文件数量: $(ls -1 "$DIST_DIR" | wc -l | tr -d ' ')"
du -sh "$DIST_DIR"
