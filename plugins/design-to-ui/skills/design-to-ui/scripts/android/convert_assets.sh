#!/usr/bin/env bash
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
# 다운로드 완료된 SVG/PNG를 Android 리소스(VectorDrawable XML / WebP)로 변환
#
# Step 4에서 download_figma_frame_images.sh로 다운로드한 뒤,
# 이 스크립트로 변환만 수행한다.
#
# 사용법:
#   bash convert_assets.sh <input_dir> <output_dir>
#
# 예시:
#   bash .claude/skills/design-to-ui/scripts/android/convert_assets.sh \
#     /tmp/figma_type_a app/src/main/res/drawable
#
# 처리:
#   SVG → preprocess_svg.py → vd-tool → 후처리 → ic_*.xml
#   PNG → cwebp -lossless → img_*.webp

set -euo pipefail

INPUT_DIR="${1:?Usage: $0 <input_dir> <output_dir>}"
OUTPUT_DIR="${2:?Usage: $0 <input_dir> <output_dir>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PREPROCESS_SCRIPT="$SCRIPT_DIR/preprocess_svg.py"
TMP_DIR="/tmp/figma_convert_$$"

# ── 의존성 검사 ──
MISSING=""
if ! command -v python3 &>/dev/null; then
  MISSING="$MISSING\n  - python3 not found"
fi
if ! command -v vd-tool &>/dev/null; then
  MISSING="$MISSING\n  - vd-tool not found. Install: npm install -g vd-tool"
fi
if [ -z "${JAVA_HOME:-}" ]; then
  if [ -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]; then
    export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
  else
    MISSING="$MISSING\n  - JAVA_HOME not set (needed by vd-tool)"
  fi
fi
if [ ! -f "$PREPROCESS_SCRIPT" ]; then
  MISSING="$MISSING\n  - preprocess_svg.py not found at $PREPROCESS_SCRIPT"
fi
if [ -n "$MISSING" ]; then
  echo -e "ERROR: Missing dependencies:$MISSING" >&2
  exit 1
fi

HAS_CWEBP=true
if ! command -v cwebp &>/dev/null; then
  echo "WARNING: cwebp not found. PNG→WebP will be skipped. Install: brew install webp"
  HAS_CWEBP=false
fi

mkdir -p "$OUTPUT_DIR"

# ── SVG 파일 수집 ──
SVG_COUNT=$(find "$INPUT_DIR" -maxdepth 1 -name '*.svg' 2>/dev/null | wc -l | tr -d ' ')
PNG_COUNT=$(find "$INPUT_DIR" -maxdepth 1 -name '*.png' 2>/dev/null | wc -l | tr -d ' ')

echo "Input: $SVG_COUNT SVG, $PNG_COUNT PNG"

if [ "$SVG_COUNT" -eq 0 ] && [ "$PNG_COUNT" -eq 0 ]; then
  echo "No SVG or PNG files found in $INPUT_DIR"
  exit 0
fi

# ── SVG → Vector Drawable XML ──
XML_CREATED=0
if [ "$SVG_COUNT" -gt 0 ]; then
  echo ""
  echo "=== SVG → Vector Drawable XML ==="
  mkdir -p "$TMP_DIR/preprocessed" "$TMP_DIR/output"

  # 전처리 (mask→clipPath, filter 제거, circle→path, opacity 변환)
  echo "  Preprocessing SVGs ..."
  python3 "$PREPROCESS_SCRIPT" "$INPUT_DIR" "$TMP_DIR/preprocessed"

  # vd-tool 변환
  echo "  Running vd-tool ..."
  vd-tool -c -in "$TMP_DIR/preprocessed" -out "$TMP_DIR/output" 2>&1 || {
    echo "WARNING: vd-tool returned non-zero. Some SVGs may have failed." >&2
  }

  # 후처리: 잔여 var(--...) 제거
  for f in "$TMP_DIR/output"/*.xml; do
    [ -f "$f" ] || continue
    sed -i '' 's/var(--[^,]*, *\([^)]*\))/\1/g' "$f" 2>/dev/null || \
    sed -i 's/var(--[^,]*, *\([^)]*\))/\1/g' "$f" 2>/dev/null || true
  done

  # drawable로 복사
  XML_CREATED=$(find "$TMP_DIR/output" -name '*.xml' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$XML_CREATED" -gt 0 ]; then
    cp "$TMP_DIR/output"/*.xml "$OUTPUT_DIR/"
    echo "  Created $XML_CREATED XML files → $OUTPUT_DIR/"
  fi
fi

# ── PNG → WebP ──
WEBP_CREATED=0
if [ "$PNG_COUNT" -gt 0 ]; then
  echo ""
  echo "=== PNG → WebP ==="
  if [ "$HAS_CWEBP" = true ]; then
    for f in "$INPUT_DIR"/*.png; do
      [ -f "$f" ] || continue
      BASENAME=$(basename "$f" .png)
      cwebp -lossless -z 9 -metadata none "$f" -o "$OUTPUT_DIR/${BASENAME}.webp" -quiet
      WEBP_CREATED=$((WEBP_CREATED + 1))
    done
    echo "  Created $WEBP_CREATED WebP files → $OUTPUT_DIR/"
  else
    echo "  Skipped (cwebp not installed)"
  fi
fi

# ── 정리 ──
rm -rf "$TMP_DIR"

echo ""
echo "=== Done ==="
[ "$XML_CREATED" -gt 0 ] && echo "  SVG → XML: $XML_CREATED files"
[ "$WEBP_CREATED" -gt 0 ] && echo "  PNG → WebP: $WEBP_CREATED files"
