#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 글리프 정체성 probe — 아이콘이 figma와 '같은 그림'인지 형태로 대조.

overlay 평균 diff는 '틀린 글리프'(십자 vs 화살표)와 '약간 어긋남'을 못 가른다. 이 스크립트는 이미 정렬된
figma.png|real.png에서 같은 아이콘 bbox를 떼어, 위치·크기를 정규화한 뒤 ink 마스크의 IoU(겹침)를 잰다.

⚠️ box에 옆 글자(예 아이콘 옆 "°")가 섞이면 IoU가 잘못 떨어져 false-positive가 난다(실측). 그래서 영역에서
**가장 큰 8-연결 ink 성분(=아이콘 본체)의 bbox로 자동 타이트닝**한 뒤 비교한다 — 떨어져 있는 이웃 글자는
배제된다. 그래도 텍스트 인접 소형 글리프는 경계 케이스가 있으니, **flag는 단정이 아니라 "직접 크롭 확인 후
재export"** 신호로 쓴다(올바른 글리프를 needless 재export하지 말 것).

큰 정체성 오류(십자↔화살표, 화살표↔캐럿)는 결정적으로 잡힌다. 비슷한 두 글리프는 임계 근처라 갈릴 수 있다.

usage:
  python3 glyph_id_probe.py <figma.png> <real.png> --regions "loc:L,T,R,B; close:L,T,R,B" [--thr 0.6] [--ink 40]
"""
import argparse
from PIL import Image


def ink_pts(imgL, box, ink_delta):
    crop = imgL.crop(box)
    px = list(crop.getdata())
    w, h = crop.size
    if not px:
        return []
    bg = sorted(px)[int(len(px) * 0.9)]
    thr = bg - ink_delta
    return [(i % w, i // w) for i, v in enumerate(px) if v < thr]


def largest_component_bbox(pts, margin_frac=0.25):
    """가장 큰 8-연결 성분(아이콘 본체)의 bbox를 margin 확장해 반환 — 떨어진 이웃 글자 배제."""
    ptset = set(pts)
    seen = set()
    best = None  # (size, minx, maxx, miny, maxy)
    for s in pts:
        if s in seen:
            continue
        stack = [s]
        seen.add(s)
        size = 0
        mnx = mxx = s[0]
        mny = mxy = s[1]
        while stack:
            x, y = stack.pop()
            size += 1
            mnx, mxx = min(mnx, x), max(mxx, x)
            mny, mxy = min(mny, y), max(mxy, y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in ptset and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if best is None or size > best[0]:
            best = (size, mnx, mxx, mny, mxy)
    _, mnx, mxx, mny, mxy = best
    mw, mh = mxx - mnx, mxy - mny
    mx, my = int(mw * margin_frac) + 2, int(mh * margin_frac) + 2
    return (mnx - mx, mny - my, mxx + mx, mxy + my)


def norm_cells(pts, tb, grid=32):
    """아이콘 본체 bbox(tb) 안의 ink만 grid 셀로 정규화 — 위치·크기 차 제거, 모양만 남김."""
    l, t, r, b = tb
    kept = [(x, y) for x, y in pts if l <= x <= r and t <= y <= b]
    if not kept:
        return set()
    xs = [p[0] for p in kept]
    ys = [p[1] for p in kept]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    return {(int((x - x0) / bw * (grid - 1)), int((y - y0) / bh * (grid - 1))) for x, y in kept}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("figma")
    ap.add_argument("real")
    ap.add_argument("--regions", required=True, help="'name:L,T,R,B; ...'")
    ap.add_argument("--thr", type=float, default=0.6, help="IoU 미만이면 형태 불일치")
    ap.add_argument("--ink", type=int, default=40)
    a = ap.parse_args()

    figL = Image.open(a.figma).convert("L")
    realL = Image.open(a.real).convert("L")
    print(f"# glyph_id_probe IoU_thr={a.thr} ink={a.ink}  (flag=크롭 확인 후 재export, 단정 아님)")
    flagged = []
    for part in a.regions.split(";"):
        part = part.strip()
        if not part:
            continue
        name, coords = part.split(":")
        box = tuple(int(v) for v in coords.split(","))
        fp = ink_pts(figL, box, a.ink)
        rp = ink_pts(realL, box, a.ink)
        if len(fp) < 10 or len(rp) < 10:
            print(f"{name.strip():>10} (ink 부족 — skip)")
            continue
        # 각자 자기 본체로 타이트닝 (이웃 글자 배제)
        fc = norm_cells(fp, largest_component_bbox(fp))
        rc = norm_cells(rp, largest_component_bbox(rp))
        iou = len(fc & rc) / (len(fc | rc) or 1)
        tag = "" if iou >= a.thr else "  <-- SHAPE MISMATCH? (크롭 확인 후, 맞으면 올바른 figma 노드로 재export)"
        if iou < a.thr:
            flagged.append(name.strip())
        print(f"{name.strip():>10} box={box} IoU={iou:.2f}{tag}")
    print(f"\n# 형태 의심 {len(flagged)}개 (크롭 확인 필요)" + ("" if flagged else " — 글리프 정체성 OK"))


if __name__ == "__main__":
    main()
