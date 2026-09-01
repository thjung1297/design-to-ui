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
#   bash convert_assets.sh <input_dir> <project_root> [unknown_scale_pngs]
#
# 예시:
#   bash .claude/skills/design-to-ui/scripts/flutter/convert_assets.sh \
#     /tmp/figma_type_a . "ic_photo.png ic_bg.png"
#
# 처리:
#   SVG (ic_*.svg, 실제 SVG 콘텐츠) → <project_root>/assets/icons/          (파일명 유지, 원본 SVG)
#   PNG (ic_*.png) → <project_root>/assets/images/2.0x/                    (ic_ → img_ 리네임, 기본값)
#     다운로드 scale=2 이므로 2.0x variant 자리에 둔다(png_nodes 경로). main(assets/images/*.png)은
#     만들지 않는다 — Flutter가 최저 해상도 variant를 fallback으로 쓴다.
#   [unknown_scale_pngs] — download_figma_frame_images.sh가 "Image-fill" 로 stderr에 알린 파일명
#     (원본 업로드 해상도라 scale=2가 아님)은 공백 구분 문자열로 여기 전달한다. 해당 PNG는
#     2.0x가 아니라 <project_root>/assets/images/(main, 1x)에 배치된다 — 임의 배율을 2배로
#     단정하지 않기 위함(잘못 단정하면 논리 크기가 실제의 절반으로 렌더된다).
#   .svg 확장자 내용 검증 — download_figma_frame_images.sh는 IMAGE-fill 노드가 벡터 자손을 갖는 등
#     드문 경우 실제로는 래스터 원본(fill 엔드포인트에서 받은 PNG/JPEG 바이트)인데 파일명만 .svg로
#     내려줄 수 있다. `<svg`/`<?xml` 마커가 없으면 진짜 SVG가 아니라고 보고, assets/icons/에
#     SvgPicture로 넣지 않는다 — 매직바이트로 실제 포맷을 판별해 unknown_scale PNG와 동일하게
#     assets/images/(main)에 배치하고 WARN을 출력한다(다운로드 스크립트는 변경하지 않음 — Flutter
#     전용 방어).
#   pubspec.yaml의 flutter.assets 선언·flutter_svg 의존은 grep으로 검증만 하고
#   미비하면 WARN을 출력한다(YAML 자동 수정은 들여쓰기 파손 위험이 있어 에이전트 Edit에 맡긴다).

set -euo pipefail

INPUT_DIR="${1:?사용법: convert_assets.sh <input_dir> <project_root> [unknown_scale_pngs]}"
PROJECT_ROOT="${2:?사용법: convert_assets.sh <input_dir> <project_root> [unknown_scale_pngs]}"
UNKNOWN_SCALE_PNGS="${3:-}"

PUBSPEC="$PROJECT_ROOT/pubspec.yaml"
ICONS_DIR="$PROJECT_ROOT/assets/icons"
IMAGES_MAIN_DIR="$PROJECT_ROOT/assets/images"
IMAGES_2X_DIR="$IMAGES_MAIN_DIR/2.0x"

# ── pubspec 존재 검증 (없으면 Flutter 프로젝트 루트가 아님) ──
if [ ! -f "$PUBSPEC" ]; then
  echo "ERROR: pubspec.yaml not found at $PUBSPEC — <project_root> 가 Flutter 프로젝트 루트가 맞는지 확인하세요." >&2
  exit 1
fi

# ── 콘텐츠 판별 헬퍼 (외부 도구 설치 불필요 — head/grep/od만 사용) ──
is_genuine_svg() {
  local f="$1" head_bytes
  head_bytes=$(head -c 300 "$f" 2>/dev/null || true)
  printf '%s' "$head_bytes" | grep -aqi '<svg' && return 0
  printf '%s' "$head_bytes" | grep -aFqi '<?xml' && return 0
  return 1
}

sniff_raster_ext() {
  local f="$1" hex
  hex=$(head -c 4 "$f" 2>/dev/null | od -An -tx1 | tr -d ' \n')
  case "$hex" in
    89504e47) echo "png" ;;
    ffd8ffdb|ffd8ffe0|ffd8ffe1|ffd8ffe2|ffd8ffe3|ffd8ffee) echo "jpg" ;;
    47494638) echo "gif" ;;
    52494646) echo "webp" ;;
    *) echo "png" ;;   # 판별 불가 시 기본값 — Flutter 이미지 디코더는 확장자가 아니라 실제 바이트로 포맷을 인식한다
  esac
}

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

# ── SVG 분류: 진짜 SVG → assets/icons/ · 오분류(래스터인데 .svg) → main PNG 취급 ──
SVG_PLACED=0
placed_png_names=()        # 2.0x-only (scale=2 확정, 개별 논리 경로 선언 필요)
placed_main_png_names=()   # main(1x, 배율 불명) — 디렉터리 선언으로 충분(직속 파일)
misclassified_names=()     # .svg로 내려왔지만 실제로는 래스터였던 원본 파일명(WARN용)
if [ "$SVG_COUNT" -gt 0 ]; then
  mkdir -p "$ICONS_DIR"
  for f in "${svgs[@]}"; do
    base="${f##*/}"
    if is_genuine_svg "$f"; then
      cp "$f" "$ICONS_DIR/"
      SVG_PLACED=$((SVG_PLACED + 1))
    else
      ext=$(sniff_raster_ext "$f")
      stem="${base%.svg}"
      case "$stem" in
        ic_*) newname="img_${stem#ic_}.$ext" ;;
        *)    newname="$stem.$ext" ;;
      esac
      mkdir -p "$IMAGES_MAIN_DIR"
      # 반대 방향 stale 정리: 같은 논리명이 이전 실행에서 2.0x로 배치돼 있었으면 제거한다.
      [ -f "$IMAGES_2X_DIR/$newname" ] && rm -f "$IMAGES_2X_DIR/$newname"
      cp "$f" "$IMAGES_MAIN_DIR/$newname"
      placed_main_png_names+=("$newname")
      misclassified_names+=("$base")
    fi
  done
  [ "$SVG_PLACED" -gt 0 ] && echo "  SVG → $ICONS_DIR ($SVG_PLACED)"
  [ "${#misclassified_names[@]}" -gt 0 ] && echo "  SVG로 내려왔지만 실제 래스터라 재분류 → $IMAGES_MAIN_DIR (${#misclassified_names[@]})"
fi

# ── PNG 배치 ──
# 기본: assets/images/2.0x/ (ic_ → img_ 리네임, scale=2 확정)
# unknown_scale_pngs에 이름이 있으면: assets/images/(main, 1x) — 임의 배율을 2배로 단정하지 않는다.
PNG_PLACED=0
if [ "$PNG_COUNT" -gt 0 ]; then
  for f in "${pngs[@]}"; do
    base="${f##*/}"
    case "$base" in
      ic_*) newname="img_${base#ic_}" ;;
      *)    newname="$base" ;;
    esac
    case " $UNKNOWN_SCALE_PNGS " in
      *" $base "*)
        mkdir -p "$IMAGES_MAIN_DIR"
        # 이전 실행에서 같은 논리명이 2.0x(scale=2)로 배치돼 있었다면 제거한다 — 안 지우면
        # main과 2.0x가 동시에 존재해 고밀도 기기가 오래된 2.0x variant를 계속 선택한다.
        [ -f "$IMAGES_2X_DIR/$newname" ] && rm -f "$IMAGES_2X_DIR/$newname"
        cp "$f" "$IMAGES_MAIN_DIR/$newname"
        placed_main_png_names+=("$newname")
        ;;
      *)
        mkdir -p "$IMAGES_2X_DIR"
        # 반대 방향: 이전에 main(1x, 배율 불명)으로 배치됐던 동일 논리명이 있으면 제거한다.
        [ -f "$IMAGES_MAIN_DIR/$newname" ] && rm -f "$IMAGES_MAIN_DIR/$newname"
        cp "$f" "$IMAGES_2X_DIR/$newname"
        placed_png_names+=("$newname")
        ;;
    esac
    PNG_PLACED=$((PNG_PLACED + 1))
  done
  [ "${#placed_png_names[@]}" -gt 0 ] && echo "  PNG(2.0x, scale=2) → $IMAGES_2X_DIR (${#placed_png_names[@]}, ic_→img_)"
  [ "${#placed_main_png_names[@]}" -gt 0 ] && echo "  PNG(main, 배율 불명) → $IMAGES_MAIN_DIR (${#placed_main_png_names[@]}, ic_→img_)"
fi

# ── pubspec 선언·의존 검증 (수정하지 않음, WARN만) ──
WARN_LINES=""
MISSING_ASSETS=""
# SVG는 assets/icons/ 직속 파일이므로 디렉터리 선언 하나로 충분하다.
# 주석·긴 문자열 안의 우연한 일치가 아니라 실제 flutter.assets 리스트 항목만 인정한다.
if [ "$SVG_PLACED" -gt 0 ] && ! grep -Eq '^[[:space:]]*-[[:space:]]+assets/icons/?[[:space:]]*(#.*)?$' "$PUBSPEC"; then
  MISSING_ASSETS="$MISSING_ASSETS    - assets/icons/\n"
fi
# main(1x, 배율 불명 — unknown_scale_pngs 및 오분류 SVG 포함) PNG는 assets/images/ 직속 파일이므로
# 디렉터리 선언 하나면 된다.
if [ "${#placed_main_png_names[@]}" -gt 0 ] && ! grep -Eq '^[[:space:]]*-[[:space:]]+assets/images/?[[:space:]]*(#.*)?$' "$PUBSPEC"; then
  MISSING_ASSETS="$MISSING_ASSETS    - assets/images/\n"
fi
# 2.0x-only(scale=2 확정) PNG는 variant뿐이라 디렉터리 선언으로는 번들되지 않는다
# (flutter_tools는 디렉터리의 직속 파일만 논리 에셋으로 열거) → 각 논리 경로를 개별 선언해야 한다.
if [ "${#placed_png_names[@]}" -gt 0 ]; then
  for name in "${placed_png_names[@]}"; do
    esc=$(printf '%s' "$name" | sed 's/\./\\./g')   # 정규식용 '.' 이스케이프
    pat="^[[:space:]]*-[[:space:]]+assets/images/${esc}[[:space:]]*(#.*)?$"
    if ! grep -Eq "$pat" "$PUBSPEC"; then
      MISSING_ASSETS="$MISSING_ASSETS    - assets/images/$name\n"
    fi
  done
fi
if [ -n "$MISSING_ASSETS" ]; then
  WARN_LINES="${WARN_LINES}WARN: pubspec.yaml flutter.assets(flutter:→assets:)에 다음 항목을 추가하세요:\n${MISSING_ASSETS}"
fi

# flutter_svg는 주석(# flutter_svg …)이 아니라 dependencies의 실제 키로 선언돼야 인정한다.
if [ "$SVG_PLACED" -gt 0 ] && ! grep -Eq '^[[:space:]]*flutter_svg[[:space:]]*:' "$PUBSPEC"; then
  WARN_LINES="${WARN_LINES}WARN: SVG를 배치했지만 pubspec.yaml에 flutter_svg 의존이 없습니다. dependencies에 flutter_svg를 추가하세요.\n"
fi

if [ "${#misclassified_names[@]}" -gt 0 ]; then
  names_joined=$(printf '%s ' "${misclassified_names[@]}")
  WARN_LINES="${WARN_LINES}WARN: 다운로드 시 .svg로 내려왔지만 실제 콘텐츠는 래스터라 assets/images/(main)로 재분류했습니다: ${names_joined}(figma-asset-download가 IMAGE-fill 노드를 SVG로 오판한 경우입니다 — Image.asset으로 참조하세요, SvgPicture 아님)\n"
fi

if [ -n "$WARN_LINES" ]; then
  echo ""
  printf "%b" "$WARN_LINES" >&2
fi

# ── 요약 ──
echo ""
echo "=== Done ==="
[ "$SVG_PLACED" -gt 0 ] && echo "  SVG ${SVG_PLACED}개 → assets/icons"
[ "${#misclassified_names[@]}" -gt 0 ] && echo "  SVG→래스터 재분류 ${#misclassified_names[@]}개 → assets/images"
[ "${#placed_png_names[@]}" -gt 0 ] && echo "  PNG ${#placed_png_names[@]}개 → assets/images/2.0x"
[ "${#placed_main_png_names[@]}" -gt 0 ] && echo "  PNG ${#placed_main_png_names[@]}개 → assets/images (main, 배율 불명)"
exit 0
