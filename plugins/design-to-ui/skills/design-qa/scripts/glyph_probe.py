#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: per-text 글자 폭·weight 프로브 — metric/align_probe가 못 보는 글리프 굵기·advance 검출.

overlay diff는 면적·평균만 보고, align_probe는 평행이동(위치)만 본다. 둘 다 **볼드/미디엄 텍스트의 글자
폭(advance)·획 굵기(weight)** 가 figma와 어긋난 것을 못 잡는다 — 위치가 맞고 metric이 floor 밴드여도
faux-bold(가변폰트 weight 미선언 → 합성 bold)나 letterSpacing 오차로 글리프 폭이 틀어질 수 있다.

이 스크립트는 텍스트 영역의 ink(잉크) 픽셀을 떼어 figma vs real을 비교한다:
- ink bbox **폭** 비율  → advance/letterSpacing (폭이 다름)
- ink **coverage**(글리프 면적 대비 잉크 비율) 비율 → weight/획 굵기 (faux-bold면 coverage↑)

판정 보조:
- coverage_ratio > 1 + thr  → real이 더 굵음 = faux-bold 의심 (가변폰트 weight 인스턴스 명시 등록)
- |width_ratio − 1| > thr    → advance 차 = letterSpacing/폰트 advance (figma tracking 직독)
- 둘 다 ~1                    → 폭/굵기 정합 (이 행은 floor 선언 가능)

usage:
  python3 glyph_probe.py <figma.png> <real.png> --regions "title:40,30,520,180; temp:60,120,360,300"
  python3 glyph_probe.py <figma.png> <real.png> --grid 6,4 [--thr 0.12] [--ink 40]
"""
import argparse
from PIL import Image


def ink_stats(imgL, box, ink_delta, mode="dark"):
    """영역의 ink(밝은 배경보다 ink_delta 이상 어두운) 픽셀 통계."""
    crop = imgL.crop(box)
    px = list(crop.getdata())
    w, h = crop.size
    if not px:
        return None
    # dark(기본): 밝은 배경 위 어두운 글자 — bg=90퍼센타일, ink=bg-delta보다 어두운 픽셀.
    # light: 컬러/어두운 배경 위 흰 글자 — bg=10퍼센타일, ink=bg+delta보다 밝은 픽셀(color_probe와 대칭).
    srt = sorted(px)
    if mode == "light":
        bg = srt[int(len(px) * 0.1)]
        thr = bg + ink_delta
        is_ink = lambda v: v > thr
    else:
        bg = srt[int(len(px) * 0.9)]
        thr = bg - ink_delta
        is_ink = lambda v: v < thr
    cols_with_ink = set()
    rows_with_ink = set()
    ink = 0
    for i, v in enumerate(px):
        if is_ink(v):
            ink += 1
            cols_with_ink.add(i % w)
            rows_with_ink.add(i // w)
    if ink == 0:
        return {"ink": 0, "bbox_w": 0, "bbox_h": 0, "coverage": 0.0}
    bbox_w = max(cols_with_ink) - min(cols_with_ink) + 1
    bbox_h = max(rows_with_ink) - min(rows_with_ink) + 1
    coverage = ink / max(1, bbox_w * bbox_h)
    return {"ink": ink, "bbox_w": bbox_w, "bbox_h": bbox_h, "coverage": round(coverage, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("figma"); ap.add_argument("real")
    ap.add_argument("--grid", default="6,4", help="cols,rows (regions 없을 때)")
    ap.add_argument("--regions", default=None, help="'name:L,T,R,B; ...'")
    ap.add_argument("--thr", type=float, default=0.12, help="width/coverage 비율 보고 임계 (0.12 = ±12%)")
    ap.add_argument("--ink", type=int, default=40, help="ink 판정: 배경 대비 N 이상 차이")
    ap.add_argument("--mode", choices=["dark", "light"], default="dark",
                    help="글자 극성: dark=밝은배경 위 어두운글자, light=컬러/어두운배경 위 흰글자")
    a = ap.parse_args()

    figL = Image.open(a.figma).convert("L")
    realL = Image.open(a.real).convert("L")
    W, H = figL.size

    boxes = []
    if a.regions:
        for part in a.regions.split(";"):
            part = part.strip()
            if not part:
                continue
            name, coords = part.split(":")
            l, t, r, b = (int(v) for v in coords.split(","))
            boxes.append((name.strip(), (l, t, r, b)))
    else:
        cols, rows = (int(v) for v in a.grid.split(","))
        cw, ch = W // cols, H // rows
        for ry in range(rows):
            for cx in range(cols):
                boxes.append((f"r{ry}c{cx}", (cx * cw, ry * ch, (cx + 1) * cw, (ry + 1) * ch)))

    print(f"# glyph_probe  thr=±{a.thr:.0%}  ink_delta={a.ink}")
    flagged = []
    for name, box in boxes:
        f = ink_stats(figL, box, a.ink, a.mode)
        r = ink_stats(realL, box, a.ink, a.mode)
        if not f or not r or f["ink"] < 20 or r["ink"] < 20:
            continue  # 텍스트 거의 없는 영역 skip
        wr = r["bbox_w"] / max(1, f["bbox_w"])
        cr = r["coverage"] / max(1e-6, f["coverage"])
        tag = ""
        if cr > 1 + a.thr:
            tag = "  <-- WEIGHT (real 더 굵음 — faux-bold 의심: 가변폰트 weight 인스턴스 명시 등록)"
            flagged.append((name, "weight", round(cr, 3)))
        elif abs(wr - 1) > a.thr:
            tag = "  <-- WIDTH (advance 차 — letterSpacing/폰트 advance figma 직독)"
            flagged.append((name, "width", round(wr, 3)))
        print(f"{name:>10} box={box} width_ratio={wr:.3f} coverage_ratio={cr:.3f}{tag}")
    print(f"\n# 글리프 폭/굵기 후보 {len(flagged)}개" + ("" if flagged else " — glyph 정합 OK"))


if __name__ == "__main__":
    main()
