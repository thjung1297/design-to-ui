#!/usr/bin/env bash
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
# 다운로드 완료된 SVG를 iOS Asset Catalog(PDF Preserve Vector Data)로 변환
#
# Step 5에서 download_figma_frame_images.sh로 다운로드한 뒤,
# 이 스크립트로 변환만 수행한다.
#
# 사용법:
#   bash convert_assets.sh <input_dir> <output_xcassets_dir>
#
# 예시:
#   bash .claude/skills/design-to-ui/scripts/ios/convert_assets.sh \
#     /tmp/figma_type_a MyApp/Assets.xcassets
#
# 처리:
#   각 SVG → (rsvg-convert|cairosvg|inkscape) → PDF
#         → <name>.imageset/{<name>.pdf, Contents.json(preserves-vector-representation)}
#   각 PNG(래스터) → <name>.imageset/{<name>.png, Contents.json(universal)}
#
# 의존성 (택1, 자동 감지):
#   brew install librsvg     # rsvg-convert (권장)
#   pip install cairosvg     # cairosvg
#   brew install inkscape    # inkscape
set -euo pipefail

INPUT_DIR="${1:?사용법: convert_assets.sh <input_dir> <output_xcassets_dir>}"
OUT_DIR="${2:?사용법: convert_assets.sh <input_dir> <output_xcassets_dir>}"

# --- 변환기 자동 선택 (SVG가 있을 때만 필수; PNG-only면 없어도 진행) ---
if command -v rsvg-convert >/dev/null 2>&1; then
  CONV=rsvg
elif command -v cairosvg >/dev/null 2>&1; then
  CONV=cairosvg
elif command -v inkscape >/dev/null 2>&1; then
  CONV=inkscape
else
  CONV=""
fi

shopt -s nullglob
svgs=("$INPUT_DIR"/*.svg)
if [ "${#svgs[@]}" -gt 0 ] && [ -z "$CONV" ]; then
  echo "ERROR: SVG→PDF 변환기가 없습니다. 다음 중 하나를 설치 후 재시도하세요:" >&2
  echo "  brew install librsvg   |   pip install cairosvg   |   brew install inkscape" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

svg2pdf() {
  local in="$1" out="$2"
  case "$CONV" in
    rsvg)     rsvg-convert -f pdf -o "$out" "$in" ;;
    cairosvg) cairosvg "$in" -f pdf -o "$out" ;;
    inkscape) inkscape "$in" --export-type=pdf --export-filename="$out" >/dev/null 2>&1 ;;
  esac
}

shopt -s nullglob
count=0
for svg in "$INPUT_DIR"/*.svg; do
  name="$(basename "$svg" .svg)"
  imgset="$OUT_DIR/$name.imageset"
  mkdir -p "$imgset"

  if ! svg2pdf "$svg" "$imgset/$name.pdf"; then
    echo "  ✗ 변환 실패: $name (스킵)" >&2
    continue
  fi

  cat > "$imgset/Contents.json" <<JSON
{
  "images" : [
    {
      "filename" : "$name.pdf",
      "idiom" : "universal"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  },
  "properties" : {
    "preserves-vector-representation" : true
  }
}
JSON

  count=$((count + 1))
  echo "  ✓ $name.imageset (pdf)"
done

# PNG(래스터) → universal imageset (벡터가 아닌 에셋. download가 PNG로 내려준 경우)
for png in "$INPUT_DIR"/*.png; do
  name="$(basename "$png" .png)"
  imgset="$OUT_DIR/$name.imageset"
  mkdir -p "$imgset"
  cp "$png" "$imgset/$name.png"

  cat > "$imgset/Contents.json" <<JSON
{
  "images" : [
    {
      "filename" : "$name.png",
      "idiom" : "universal"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
JSON

  count=$((count + 1))
  echo "  ✓ $name.imageset (png)"
done

if [ "$count" -eq 0 ]; then
  echo "변환할 SVG/PNG가 없습니다: $INPUT_DIR" >&2
  exit 1
fi

echo "변환 완료: ${count}개 imageset → $OUT_DIR (벡터 변환기: $CONV)"
