#!/usr/bin/env bash
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
# 다운로드 완료된 SVG/PNG를 Flutter 에셋 위치로 배치한다.
#
# Flutter는 SVG를 원본 그대로 flutter_svg로 렌더하므로 변환 도구가 필요 없다 —
# 이 스크립트는 복사·리네임·검증만 수행한다.
#
# Step 5에서 download_figma_frame_images.sh로 다운로드한 뒤 이 스크립트를 돌린다.
#
# 사용법:
#   bash convert_assets.sh <input_dir> <project_root>
#
# 예시:
#   bash .claude/skills/design-to-ui/scripts/flutter/convert_assets.sh \
#     /tmp/figma_type_a .
#
# 처리:
#   SVG (ic_*.svg) → <project_root>/assets/icons/           (파일명 유지, 원본 SVG)
#   PNG (ic_*.png) → <project_root>/assets/images/2.0x/     (ic_ → img_ 리네임)
#     다운로드 scale=2 이므로 2.0x variant 자리에 둔다. main(assets/images/*.png)은
#     만들지 않는다 — Flutter가 최저 해상도 variant를 fallback으로 쓴다.
#   pubspec.yaml의 flutter.assets 선언·flutter_svg 의존은 grep으로 검증만 하고
#   미비하면 WARN을 출력한다(YAML 자동 수정은 들여쓰기 파손 위험이 있어 에이전트 Edit에 맡긴다).

set -euo pipefail

INPUT_DIR="${1:?사용법: convert_assets.sh <input_dir> <project_root>}"
PROJECT_ROOT="${2:?사용법: convert_assets.sh <input_dir> <project_root>}"

PUBSPEC="$PROJECT_ROOT/pubspec.yaml"
ICONS_DIR="$PROJECT_ROOT/assets/icons"
IMAGES_2X_DIR="$PROJECT_ROOT/assets/images/2.0x"

# ── pubspec 존재 검증 (없으면 Flutter 프로젝트 루트가 아님) ──
if [ ! -f "$PUBSPEC" ]; then
  echo "ERROR: pubspec.yaml not found at $PUBSPEC — <project_root> 가 Flutter 프로젝트 루트가 맞는지 확인하세요." >&2
  exit 1
fi

# ── 입력 수집 (bash 3.2 호환: nullglob) ──
shopt -s nullglob
svgs=("$INPUT_DIR"/*.svg)
pngs=("$INPUT_DIR"/*.png)
SVG_COUNT="${#svgs[@]}"
PNG_COUNT="${#pngs[@]}"

echo "Input: $SVG_COUNT SVG, $PNG_COUNT PNG"

if [ "$SVG_COUNT" -eq 0 ] && [ "$PNG_COUNT" -eq 0 ]; then
  echo "No SVG or PNG files found in $INPUT_DIR"
  exit 0
fi

# ── SVG → assets/icons/ (파일명 유지) ──
SVG_PLACED=0
if [ "$SVG_COUNT" -gt 0 ]; then
  mkdir -p "$ICONS_DIR"
  for f in "${svgs[@]}"; do
    cp "$f" "$ICONS_DIR/"
    SVG_PLACED=$((SVG_PLACED + 1))
  done
  echo "  SVG → $ICONS_DIR ($SVG_PLACED)"
fi

# ── PNG → assets/images/2.0x/ (ic_ → img_ 리네임) ──
PNG_PLACED=0
placed_png_names=()
if [ "$PNG_COUNT" -gt 0 ]; then
  mkdir -p "$IMAGES_2X_DIR"
  for f in "${pngs[@]}"; do
    base="${f##*/}"
    case "$base" in
      ic_*) newname="img_${base#ic_}" ;;
      *)    newname="$base" ;;
    esac
    cp "$f" "$IMAGES_2X_DIR/$newname"
    placed_png_names+=("$newname")
    PNG_PLACED=$((PNG_PLACED + 1))
  done
  echo "  PNG → $IMAGES_2X_DIR ($PNG_PLACED, ic_→img_)"
fi

# ── pubspec 선언·의존 검증 (수정하지 않음, WARN만) ──
WARN_LINES=""
MISSING_ASSETS=""
# SVG는 assets/icons/ 직속 파일이므로 디렉터리 선언 하나로 충분하다.
if [ "$SVG_PLACED" -gt 0 ] && ! grep -q 'assets/icons/' "$PUBSPEC"; then
  MISSING_ASSETS="$MISSING_ASSETS    - assets/icons/\n"
fi
# PNG는 2.0x/ variant만 있고 main 1x가 없으므로 디렉터리 선언으로는 번들되지 않는다
# (flutter_tools는 디렉터리의 직속 파일만 논리 에셋으로 열거) → 각 논리 경로를 개별 선언해야 한다.
if [ "$PNG_PLACED" -gt 0 ]; then
  for name in "${placed_png_names[@]}"; do
    if ! grep -q "assets/images/$name" "$PUBSPEC"; then
      MISSING_ASSETS="$MISSING_ASSETS    - assets/images/$name\n"
    fi
  done
fi
if [ -n "$MISSING_ASSETS" ]; then
  WARN_LINES="${WARN_LINES}WARN: pubspec.yaml flutter.assets(flutter:→assets:)에 다음 항목을 추가하세요:\n${MISSING_ASSETS}"
fi

if [ "$SVG_PLACED" -gt 0 ] && ! grep -q 'flutter_svg' "$PUBSPEC"; then
  WARN_LINES="${WARN_LINES}WARN: SVG를 배치했지만 pubspec.yaml에 flutter_svg 의존이 없습니다. dependencies에 flutter_svg를 추가하세요.\n"
fi

if [ -n "$WARN_LINES" ]; then
  echo ""
  printf "%b" "$WARN_LINES" >&2
fi

# ── 요약 ──
echo ""
echo "=== Done ==="
[ "$SVG_PLACED" -gt 0 ] && echo "  SVG ${SVG_PLACED}개 → assets/icons"
[ "$PNG_PLACED" -gt 0 ] && echo "  PNG ${PNG_PLACED}개 → assets/images/2.0x"
exit 0
