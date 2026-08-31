#!/usr/bin/env bash
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
# Figma REST API로 에셋(아이콘·이미지)을 다운로드.
# 전제: 환경 변수 FIGMA_ACCESS_TOKEN (Personal Access Token)
#
# 사용법 1 — 개별 node ID 지정 (design-to-ui Step 4 분류 결과 사용):
#   download_figma_frame_images.sh <file_key> <output_dir> <node_id_1> [node_id_2] ...
#   예: bash download_figma_frame_images.sh <FILE_KEY> /tmp/assets 1234:5678 1234:5679
#
# 사용법 2 — 프레임 전체 스캔 (기존 방식, --scan 플래그):
#   download_figma_frame_images.sh --scan <file_key> <frame_node_id> <output_dir>
#   예: bash download_figma_frame_images.sh --scan <FILE_KEY> 1234:5678 /tmp/assets
#
# 포맷 판단 (공통):
#   1순위: exportSettings가 있으면 → 디자이너 지정 포맷(SVG/PNG) 사용
#   2순위: VECTOR 계열 하위 노드가 있으면 → 벡터 그래픽으로 판단, SVG
#   3순위: 위 조건 모두 아니면 → 래스터 이미지로 판단, PNG
#
# 개별 모드: 지정된 node ID의 노드 정보를 조회 → 포맷 판단 → 다운로드.
# 스캔 모드: 프레임 하위 전체를 순회하여 에셋을 자동 발견 → 포맷 판단 → 다운로드.
#   에셋 발견 전략:
#     - TEXT 하위 노드가 없는 INSTANCE/COMPONENT → 아이콘
#     - leaf FRAME (VECTOR 있음 + TEXT 없음 + 자식 FRAME 없음) → 벡터 그래픽
#     - TEXT가 섞인 레이아웃 프레임, 최상위 화면 프레임 → 제외
#     - componentId 기준 중복 제거로 동일 아이콘 인스턴스를 1회만 다운로드

set -e

if [ -z "$FIGMA_ACCESS_TOKEN" ]; then
  echo "ERROR: FIGMA_ACCESS_TOKEN not set. Set it (e.g. in ~/.zshrc)." >&2
  exit 1
fi

# ── 인자 파싱 ──
if [ "$1" = "--scan" ]; then
  MODE="scan"
  shift
  FILE_KEY="${1:?Usage: $0 --scan <file_key> <frame_node_id> <output_dir>}"
  FRAME_NODE_ID="${2:?Usage: $0 --scan <file_key> <frame_node_id> <output_dir>}"
  OUTPUT_DIR="${3:?Usage: $0 --scan <file_key> <frame_node_id> <output_dir>}"
  IDS_TO_FETCH="$FRAME_NODE_ID"
  DEPTH="&depth=10"
else
  MODE="direct"
  FILE_KEY="${1:?Usage: $0 <file_key> <output_dir> <node_id_1> [node_id_2] ...}"
  OUTPUT_DIR="${2:?Usage: $0 <file_key> <output_dir> <node_id_1> [node_id_2] ...}"
  shift 2
  if [ $# -eq 0 ]; then
    echo "ERROR: At least one node ID is required." >&2
    exit 1
  fi
  IDS_TO_FETCH=$(IFS=,; echo "$*")
  FRAME_NODE_ID=""
  DEPTH=""
fi

mkdir -p "$OUTPUT_DIR"

# ── Figma API로 노드 정보 조회 ──
ENCODED_IDS=$(echo "$IDS_TO_FETCH" | sed 's/:/%3A/g')
echo "Fetching node info ($MODE mode) ..."
NODES_JSON=$(curl -sf -H "X-Figma-Token: $FIGMA_ACCESS_TOKEN" \
  "https://api.figma.com/v1/files/${FILE_KEY}/nodes?ids=${ENCODED_IDS}${DEPTH}") \
  || { echo "ERROR: Figma API /nodes request failed." >&2; exit 1; }

# ── Python: 수집 + 포맷 판단 + 다운로드 ──
echo "$NODES_JSON" | MODE="$MODE" FRAME_NODE_ID="$FRAME_NODE_ID" \
  FILE_KEY="$FILE_KEY" FIGMA_ACCESS_TOKEN="$FIGMA_ACCESS_TOKEN" OUTPUT_DIR="$OUTPUT_DIR" \
  python3 -c "
import sys, json, os, subprocess, re, urllib.request, urllib.parse

# ── 설정 ──
mode       = os.environ['MODE']
frame_id   = os.environ.get('FRAME_NODE_ID', '')
file_key   = os.environ['FILE_KEY']
token      = os.environ['FIGMA_ACCESS_TOKEN']
out_dir    = os.environ['OUTPUT_DIR']
if not os.path.isabs(out_dir):
    out_dir = os.path.abspath(out_dir)
os.makedirs(out_dir, exist_ok=True)

d = json.load(sys.stdin)
if d.get('err'):
    print('ERROR: Figma API error:', d.get('err'), file=sys.stderr)
    sys.exit(1)

nodes_map = d.get('nodes') or {}

svg_nodes  = []
png_nodes  = []
fill_nodes = []
seen_names = {}

VECTOR_TYPES = {'VECTOR', 'BOOLEAN_OPERATION', 'ELLIPSE', 'STAR', 'LINE', 'REGULAR_POLYGON'}

# ═══════════════════════════════════════════════
# 공통 유틸리티
# ═══════════════════════════════════════════════

def to_snake(name, nid=''):
    s = name.strip()
    s = re.sub(r'[/\\\\\\\\]', '_', s)
    s = re.sub(r'[^a-zA-Z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    s = s.lower()
    if not s:
        s = re.sub(r'[^a-zA-Z0-9_]', '_', nid)
    return s

def unique_name(base):
    if base not in seen_names:
        seen_names[base] = 0
        return base
    seen_names[base] += 1
    return f'{base}_{seen_names[base]}'

def get_image_ref(n):
    for fill in (n.get('fills') or []):
        if isinstance(fill, dict) and fill.get('type') == 'IMAGE' and fill.get('imageRef'):
            return fill['imageRef']
    return None

def has_vector_descendant(n):
    if not isinstance(n, dict):
        return False
    if n.get('type') in VECTOR_TYPES:
        return True
    for c in n.get('children', []):
        if has_vector_descendant(c):
            return True
    return False

def decide_format(n):
    \"\"\"공통 포맷 판단: exportSettings → 벡터 판단 → PNG 기본\"\"\"
    es = n.get('exportSettings') or []
    if es:
        fmt = (es[0].get('format') or 'SVG').lower()
        return fmt if fmt in ('svg', 'png') else 'svg'
    if has_vector_descendant(n):
        return 'svg'
    return 'png'

def collect(nid, name, fmt, n):
    ref = get_image_ref(n)
    base = 'ic_' + to_snake(name, nid)
    fname = unique_name(base) + '.' + fmt
    if ref:
        fill_nodes.append((nid, fname, ref))
    elif fmt == 'png':
        png_nodes.append((nid, fname))
    else:
        svg_nodes.append((nid, fname))

# ═══════════════════════════════════════════════
# 수집: 모드에 따라 분기
# ═══════════════════════════════════════════════

if mode == 'direct':
    # 개별 모드: 지정된 node ID의 포맷만 판단
    for nid, node_data in nodes_map.items():
        doc = node_data.get('document') or {}
        collect(nid, doc.get('name', nid), decide_format(doc), doc)

else:
    # 스캔 모드: 프레임 하위를 순회하여 에셋 자동 발견
    doc = (nodes_map.get(frame_id) or {}).get('document')
    if not doc and len(nodes_map) == 1:
        doc = list(nodes_map.values())[0].get('document') or {}
    doc = doc or {}

    seen_component_ids = set()

    def has_text_descendant(n):
        if not isinstance(n, dict):
            return False
        if n.get('type') == 'TEXT':
            return True
        return any(has_text_descendant(c) for c in n.get('children', []))

    def has_frame_child(n):
        return any(
            isinstance(c, dict) and c.get('type') == 'FRAME'
            for c in n.get('children', [])
        )

    def walk(n, is_root=False):
        if not isinstance(n, dict):
            return
        nid  = n.get('id', '')
        name = n.get('name', nid)
        typ  = n.get('type', '')
        cid  = n.get('componentId', '')
        es   = n.get('exportSettings') or []

        has_export   = bool(es) and not is_root
        is_component = typ in ('INSTANCE', 'COMPONENT') and not is_root
        is_vector_frame = (typ == 'FRAME'
                           and not is_root
                           and has_vector_descendant(n)
                           and not has_text_descendant(n)
                           and not has_frame_child(n))

        if nid and (has_export or is_component or is_vector_frame):
            if cid and cid in seen_component_ids:
                return
            if not has_text_descendant(n) and has_vector_descendant(n):
                if cid:
                    seen_component_ids.add(cid)
                collect(nid, name, decide_format(n), n)
                return

        for c in n.get('children', []):
            walk(c)

    for c in doc.get('children', []):
        walk(c, is_root=False)

if not svg_nodes and not png_nodes and not fill_nodes:
    print('No exportable nodes found.', file=sys.stderr)
    sys.exit(0)

print(f'Found {len(svg_nodes)} SVG, {len(png_nodes)} PNG, {len(fill_nodes)} image-fill nodes.')

# ═══════════════════════════════════════════════
# 공통 다운로드
# ═══════════════════════════════════════════════

def api_get(url):
    req = urllib.request.Request(url, headers={'X-Figma-Token': token})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def download(url, path):
    subprocess.run(['curl', '-sf', '-o', path, url], check=True)

downloaded = []

if svg_nodes:
    ids_str = ','.join(nid for nid, _ in svg_nodes)
    encoded = urllib.parse.quote(ids_str, safe=',')
    resp = api_get(f'https://api.figma.com/v1/images/{file_key}?ids={encoded}&format=svg')
    images = resp.get('images') or {}
    for nid, fname in svg_nodes:
        url = images.get(nid)
        if not url:
            print(f'  SKIP (no URL): {nid}', file=sys.stderr)
            continue
        fpath = os.path.join(out_dir, fname)
        download(url, fpath)
        downloaded.append(fpath)
        print(fpath)

if png_nodes:
    ids_str = ','.join(nid for nid, _ in png_nodes)
    encoded = urllib.parse.quote(ids_str, safe=',')
    resp = api_get(f'https://api.figma.com/v1/images/{file_key}?ids={encoded}&format=png&scale=2')
    images = resp.get('images') or {}
    for nid, fname in png_nodes:
        url = images.get(nid)
        if not url:
            print(f'  SKIP (no URL): {nid}', file=sys.stderr)
            continue
        fpath = os.path.join(out_dir, fname)
        download(url, fpath)
        downloaded.append(fpath)
        print(fpath)

if fill_nodes:
    resp = api_get(f'https://api.figma.com/v1/files/{file_key}/images')
    meta_images = (resp.get('meta') or {}).get('images') or {}
    for nid, fname, ref in fill_nodes:
        url = meta_images.get(ref)
        if not url:
            print(f'  SKIP (no imageRef URL): {nid} ref={ref}', file=sys.stderr)
            continue
        fpath = os.path.join(out_dir, fname)
        download(url, fpath)
        downloaded.append(fpath)
        print(fpath)

if fill_nodes:
    # image-fill 다운로드는 원본 업로드 해상도(임의 배율)라 png_nodes(scale=2 고정)와 다르다.
    # 플랫폼 변환 스크립트(예: Flutter convert_assets.sh)가 2x 단정을 피할 수 있도록 파일명을 별도로 알린다.
    fill_fnames = [fname for _, fname, _ in fill_nodes if os.path.join(out_dir, fname) in downloaded]
    if fill_fnames:
        print('Image-fill (원본 업로드 해상도, scale=2 아님): ' + ' '.join(fill_fnames), file=sys.stderr)

print(f'Done. {len(downloaded)} files saved under {out_dir}', file=sys.stderr)
"
