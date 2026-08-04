#!/usr/bin/env python3
"""design-qa: probe region 열거 — 무엇을 검사할지를 Figma 노드에서 **기계적으로** 정한다.

왜 필요한가. `glyph_id_probe`·`glyph_probe`·`color_probe`·`edge_probe` 는 모두 `--regions "name:L,T,R,B"`
를 받는데, 그 좌표를 만드는 경로가 스킬에 없었다. 실제로는 `overlay` 의 `suspect_regions`(면적 평균 top-N)
를 모델이 눈으로 보고 손으로 만들었다. 그래서:

  - **세션마다 검사 대상이 달라졌다** — 같은 화면을 두 번 돌려도 region 목록이 다르다("probing 이 될 때도
    안 될 때도 있다"의 정체는 신뢰도가 아니라 **커버리지**다).
  - **면적 평균이 후보를 정하므로 작은 아이콘·얇은 선은 애초에 후보로 올라오지 않는다** — 검사 대상에서
    구조적으로 빠진다.

이 스크립트는 열거를 **화면 내용(Figma 노드)** 으로 결정한다. 같은 입력 → 같은 region 목록(정렬 고정)이므로
세션 간 재현성이 생기고, 열거 수를 ledger 커버리지 근거로 쓸 수 있다(`ledger_gate.py` 의 coverage 검사).

입력: Figma metadata. **두 형태를 모두 받는다** — 실측으로 확인된 차이다.
  - **MCP XML** (figma-desktop `get_metadata` 의 실제 응답). `<frame id=… x= y= width= height=>` 중첩이고
    좌표가 **부모 기준 상대값**이라 누적해서 프레임 원점 기준으로 만든다. 타입은 태그명이다
    (`boolean-operation` → BOOLEAN_OPERATION 등). ⚠️ fills 가 없어 `--emit color` 의 기대 hex 는 못 만든다.
  - **REST JSON** (`/v1/files/:key/nodes?ids=`). `absoluteBoundingBox` 절대 좌표 + `fills` 를 준다.
응답을 그대로 파일로 저장해 넘기면 된다(SKILL 워크플로우 3b) — 첫 글자로 XML/JSON 을 판별한다.

좌표 변환: 프레임 원점 기준 상대 dp → `× --scale`(캡처 px per dp).
`--scale` 은 캡처 배율이다(예: 360dp 프레임을 1080px 로 캡처 = 3).

kind:
  glyph  — VECTOR/BOOLEAN_OPERATION 등 벡터 + 작은 INSTANCE/COMPONENT(아이콘). `glyph_id_probe`(모양)와
           `glyph_id_probe --size-check`(크기=asset_size 행) 대상.
  text   — TEXT 노드. `glyph_probe`(advance/weight) 대상. 색 토큰이 붙어 있으면 `color_probe` 기대 hex 도 함께 낸다.
  edge   — 프레임 폭(또는 높이)까지 뻗는 **얇은** 노드(구분선·보더·full-bleed 배경). `edge_probe` 대상.
           면적 평균·`pct_over_32` 로는 원리적으로 안 잡히는 카테고리라 열거가 유일한 진입이다.

usage:
  python3 enumerate_regions.py <meta.xml|meta.json> --scale 3             # 전체 kind JSON
  python3 enumerate_regions.py <meta> --scale 3 --emit glyph              # region 문자열만 (shell 대입용)
  python3 enumerate_regions.py <meta> --scale 3 --emit edge
  python3 enumerate_regions.py <meta> --scale 3 --frame-node 122:533      # 프레임 명시(기본: 최상위 FRAME 자동)
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

# 아이콘으로 볼 INSTANCE/COMPONENT 의 최대 변 길이(dp). 이보다 크면 카드·패널로 보고 glyph 대상에서 뺀다.
ICON_MAX_DP = 48
# edge(구분선/보더) 판정: 이 두께(dp) 이하 && 프레임 변 길이의 (1 - EDGE_SPAN_TOL) 이상을 덮는 노드.
EDGE_MAX_THICK_DP = 2.0
EDGE_SPAN_TOL_DP = 2.0
# glyph region 에 붙일 여유(노드 크기 비율, 최소 px). probe 가 배경 밝기를 추정해야 하므로 **타이트 bbox
# 를 그대로 주면 안 된다** — 박스가 전부 잉크면 배경 추정이 무너진다(실측: 체크 아이콘 bbox 를 그대로 줬을 때
# 90퍼센타일이 글리프 자신이 되어 대비 15 로 읽혔다). probe 는 안에서 다시 본체로 타이트닝하므로 여유는 안전하다.
GLYPH_MARGIN_FRAC = 0.35
GLYPH_MARGIN_MIN_PX = 6
# 벡터 계열 타입 — 크기와 무관하게 glyph 대상.
VECTOR_TYPES = {"VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON", "ELLIPSE", "LINE"}
CONTAINER_TYPES = {"FRAME", "GROUP", "COMPONENT_SET", "SECTION", "CANVAS", "DOCUMENT", "PAGE"}


def load_meta(path):
    """metadata 파일을 읽어 노드 트리(dict) 로. MCP XML / REST·MCP JSON 양쪽을 받는다."""
    raw = open(path, encoding="utf-8").read().strip()
    if not raw:
        sys.exit(f"enumerate_regions: {path} 가 비어 있다")
    if raw[0] == "<":
        return xml_to_tree(raw)
    try:
        return json.loads(raw)
    except Exception as e:
        sys.exit(f"enumerate_regions: {path} 를 XML·JSON 둘 다로 못 읽었다: {e}")


def xml_to_tree(raw):
    """MCP get_metadata XML → JSON 트리. 상대 좌표를 누적해 absoluteBoundingBox 를 만든다.

    MCP 응답은 노드 뒤에 안내문이 붙어 올 수 있어(툴 설명 텍스트) 마지막 닫는 태그까지만 잘라 파싱한다.
    """
    end = raw.rfind(">")
    if end != -1:
        raw = raw[:end + 1]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        sys.exit(f"enumerate_regions: MCP XML 파싱 실패: {e}")

    def conv(el, ox, oy):
        # 태그명이 타입이다: frame → FRAME, boolean-operation → BOOLEAN_OPERATION
        t = el.tag.replace("-", "_").upper()
        try:
            x = ox + float(el.get("x", 0))
            y = oy + float(el.get("y", 0))
            w = float(el.get("width", 0))
            h = float(el.get("height", 0))
        except ValueError:
            x = y = w = h = 0.0
        node = {
            "id": el.get("id"), "name": el.get("name"), "type": t,
            "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
            "children": [conv(c, x, y) for c in list(el)],
        }
        if el.get("visible") == "false":
            node["visible"] = False
        return node

    return conv(root, 0.0, 0.0)


def _bbox(node):
    """노드의 absolute bbox 를 (x, y, w, h) 로. MCP/REST/flat 어느 형태든 받는다."""
    for key in ("absoluteBoundingBox", "absoluteRenderBounds", "boundingBox", "bbox"):
        b = node.get(key)
        if isinstance(b, dict) and b.get("width") is not None and b.get("height") is not None:
            return (float(b.get("x", 0)), float(b.get("y", 0)), float(b["width"]), float(b["height"]))
    if node.get("width") is not None and node.get("height") is not None and node.get("x") is not None:
        return (float(node["x"]), float(node["y"]), float(node["width"]), float(node["height"]))
    return None


def _children(node):
    for key in ("children", "nodes", "items"):
        c = node.get(key)
        if isinstance(c, list):
            return c
        if isinstance(c, dict):                      # REST /nodes 는 {id: {document: {...}}} 형태
            return [v.get("document", v) if isinstance(v, dict) else v for v in c.values()]
    return []


def walk(root):
    """노드 트리를 평탄화 — (node, depth). id/type 을 가진 dict 만 노드로 본다.

    BOOLEAN_OPERATION 내부로는 내려가지 않는다 — 그 자식들은 불리언 연산의 **구성 벡터**이지 별개
    아이콘이 아니다. 내려가면 같은 글리프를 여러 region 으로 중복 열거한다(실측: REST JSON 은 CheckIcon
    하나를 6개로 열거했고 MCP XML 은 애초에 자식을 안 준다 — 이 가드로 두 경로가 일치한다).
    """
    out = []

    def rec(n, depth):
        if not isinstance(n, dict):
            return
        node = n.get("document", n) if isinstance(n.get("document"), dict) else n
        if node.get("type") is not None:
            out.append((node, depth))
            depth += 1
            if node["type"] == "BOOLEAN_OPERATION":
                return
        for c in _children(node):
            rec(c, depth)

    if isinstance(root, dict):
        # 최상위가 {nodes: {...}} 나 {document: {...}} 래핑이어도 rec 가 알아서 내려간다.
        rec(root, 0)
        for c in _children(root):
            rec(c, 0)
    elif isinstance(root, list):
        for c in root:
            rec(c, 0)
    # 같은 노드가 두 경로로 들어올 수 있으니 id 기준 dedup (얕은 depth 우선).
    seen = {}
    for node, depth in out:
        nid = node.get("id") or f"@{id(node)}"
        if nid not in seen or depth < seen[nid][1]:
            seen[nid] = (node, depth)
    return list(seen.values())


def pick_frame(nodes, frame_node):
    """기준 프레임 선택 — 명시 id 우선, 없으면 bbox 가 가장 큰 FRAME/COMPONENT."""
    if frame_node:
        want = frame_node.replace("-", ":")
        for node, _ in nodes:
            if str(node.get("id", "")).replace("-", ":") == want:
                return node
        sys.exit(f"enumerate_regions: --frame-node {frame_node} 를 metadata 에서 못 찾음")
    cands = [n for n, _ in nodes
             if n.get("type") in ("FRAME", "COMPONENT", "INSTANCE") and _bbox(n)]
    if not cands:
        cands = [n for n, _ in nodes if _bbox(n)]
    if not cands:
        sys.exit("enumerate_regions: absoluteBoundingBox 를 가진 노드가 없음 — metadata 형태 확인")
    return max(cands, key=lambda n: _bbox(n)[2] * _bbox(n)[3])


def _visible(node):
    return node.get("visible", True) is not False


def _color_hex(node):
    """TEXT 노드의 단색 fill 을 #rrggbb 로 — color_probe 기대값. 없으면 None."""
    fills = node.get("fills")
    if not isinstance(fills, list):
        return None
    for f in fills:
        if not isinstance(f, dict) or f.get("visible") is False:
            continue
        if f.get("type") != "SOLID":
            continue
        c = f.get("color")
        if not isinstance(c, dict):
            continue
        return "#%02x%02x%02x" % tuple(max(0, min(255, round(c.get(k, 0) * 255))) for k in ("r", "g", "b"))
    return None


def _safe_name(node, used):
    raw = str(node.get("name") or node.get("type") or "node")
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", raw).strip("-") or "node"
    nid = str(node.get("id", "")).replace(":", "_")
    key = name
    if key in used:                      # 같은 이름이 여러 개면 node id 를 붙여 유일화 (결정적)
        key = f"{name}#{nid}" if nid else f"{name}#{used[name]}"
    used[name] = used.get(name, 1) + 1
    return key


def classify(nodes, frame, scale, icon_max_dp, edge_thick_dp, edge_tol_dp):
    fx, fy, fw, fh = _bbox(frame)
    fid = frame.get("id")
    out = {"glyph": [], "text": [], "edge": []}
    used = {}
    rows = []
    for node, _ in nodes:
        if node.get("id") == fid or not _visible(node):
            continue
        b = _bbox(node)
        if not b:
            continue
        x, y, w, h = b
        if w <= 0 or h <= 0:
            continue
        # 프레임 밖 노드 제외 (다른 프레임의 노드가 같은 응답에 섞여 오는 경우)
        if x + w < fx or x > fx + fw or y + h < fy or y > fy + fh:
            continue
        rows.append((node, x - fx, y - fy, w, h))
    # 정렬 고정 — (y, x, id). 같은 입력이면 항상 같은 순서/이름이 나온다.
    rows.sort(key=lambda r: (round(r[2], 2), round(r[1], 2), str(r[0].get("id", ""))))

    for node, rx, ry, w, h in rows:
        t = node.get("type")
        px = lambda v: int(round(v * scale))
        box = (px(rx), px(ry), px(rx + w), px(ry + h))
        entry = {
            "name": _safe_name(node, used),
            "node_id": node.get("id"),
            "type": t,
            "box": list(box),
            "figma_dp": [round(w, 2), round(h, 2)],
        }
        # edge — 프레임 변까지 뻗는 얇은 노드. 가로/세로 둘 다 본다.
        horiz = h <= edge_thick_dp and w >= fw - edge_tol_dp
        vert = w <= edge_thick_dp and h >= fh - edge_tol_dp
        if (horiz or vert) and t not in CONTAINER_TYPES:
            e = dict(entry)
            e["axis"] = "h" if horiz else "v"
            e["expect_span_px"] = [px(0), px(fw if horiz else fh)]
            out["edge"].append(e)
            continue
        if t == "TEXT":
            e = dict(entry)
            hexv = _color_hex(node)
            if hexv:
                e["expect_hex"] = hexv
            out["text"].append(e)
            continue
        if t in VECTOR_TYPES or (t in ("INSTANCE", "COMPONENT") and max(w, h) <= icon_max_dp):
            e = dict(entry)
            # glyph 박스에는 여유를 준다 — probe 가 배경 밝기를 추정해야 하고, 타이트 bbox 는 박스 전체가
            # 잉크라 그 추정이 무너진다. probe 가 안에서 본체로 다시 타이트닝하므로 여유는 판정을 안 흐린다.
            mx = max(GLYPH_MARGIN_MIN_PX, int(round(w * scale * GLYPH_MARGIN_FRAC)))
            my = max(GLYPH_MARGIN_MIN_PX, int(round(h * scale * GLYPH_MARGIN_FRAC)))
            e["box"] = [box[0] - mx, box[1] - my, box[2] + mx, box[3] + my]
            e["tight_box"] = list(box)          # 여유 없는 원본 bbox (기대 크기 근거)
            out["glyph"].append(e)
    return out, (fw, fh)


def regions_str(entries, with_hex=False):
    parts = []
    for e in entries:
        l, t, r, b = e["box"]
        s = f"{e['name']}:{l},{t},{r},{b}"
        if with_hex and e.get("expect_hex"):
            s += f"={e['expect_hex']}"
        parts.append(s)
    return "; ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("meta", help="get_metadata(MCP XML) 또는 REST nodes(JSON) 응답을 저장한 파일")
    ap.add_argument("--scale", type=float, required=True, help="캡처 px per dp (예: 360dp→1080px 이면 3)")
    ap.add_argument("--frame-node", default=None, help="기준 프레임 node id (기본: 가장 큰 FRAME 자동)")
    ap.add_argument("--emit", choices=["glyph", "text", "edge", "color"], default=None,
                    help="해당 kind 의 region 문자열만 출력 (shell 대입용)")
    ap.add_argument("--icon-max-dp", type=float, default=ICON_MAX_DP)
    ap.add_argument("--edge-thick-dp", type=float, default=EDGE_MAX_THICK_DP)
    ap.add_argument("--edge-tol-dp", type=float, default=EDGE_SPAN_TOL_DP)
    a = ap.parse_args()

    root = load_meta(a.meta)
    nodes = walk(root)
    if not nodes:
        sys.exit("enumerate_regions: 노드를 못 찾음 — get_metadata 응답을 그대로 저장했는지 확인")
    frame = pick_frame(nodes, a.frame_node)
    kinds, (fw, fh) = classify(nodes, frame, a.scale, a.icon_max_dp, a.edge_thick_dp, a.edge_tol_dp)

    if a.emit == "color":
        print(regions_str([e for e in kinds["text"] if e.get("expect_hex")], with_hex=True))
        return
    if a.emit:
        print(regions_str(kinds[a.emit]))
        return

    result = {
        "frame": {"node_id": frame.get("id"), "name": frame.get("name"),
                  "dp": [round(fw, 2), round(fh, 2)], "scale": a.scale,
                  "expect_capture_px": [int(round(fw * a.scale)), int(round(fh * a.scale))]},
        # ledger 커버리지 근거 — 이 수가 '열거 수'다. 검사 수가 이보다 적으면 ledger_gate 가 FAIL 한다.
        "counts": {k: len(v) for k, v in kinds.items()},
        "regions": {k: regions_str(v, with_hex=(k == "text")) for k, v in kinds.items()},
        "nodes": kinds,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
