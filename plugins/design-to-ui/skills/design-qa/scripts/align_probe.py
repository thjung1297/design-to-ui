#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: per-block 정렬 프로브 — 블록 단위 위치 드리프트 검출.

overlay diff/top-N 은 '면적 큰 요소'에 끌려 작은 텍스트 블록의 위치 어긋남(헤더가 가로로 밀림,
카드 라벨이 세로로 밀림 등)을 놓친다. 이 스크립트는 figma|real 을 격자(또는 지정 영역)로 나눠
각 칸에서 **MAE를 최소화하는 best (dx,dy) 시프트**를 찾아, 시프트가 임계 이상인 칸을
'블록 위치 드리프트(layout 오차)' 후보로 보고한다. 전역 정렬이 0인데 특정 칸만 dx/dy가 크면
그 블록의 padding/arrangement/letterSpacing 이 figma와 다른 것.

판정 보조:
- |dx|,|dy| 큼 + 시프트로 MAE 크게↓  → 블록 위치 드리프트(코드 수정: padding/offset/gap)
- dy가 글자 크기에 비례(큰 텍스트 칸일수록 큼) → 폰트 메트릭(includeFontPadding/lineHeight)
- 시프트해도 MAE 안 줄고 균일 ≤1px → Skia AA(불가역)

usage:
  python3 align_probe.py <figma.png> <real.png> [--grid 6,4] [--range 20] [--thr 4]
  python3 align_probe.py <figma.png> <real.png> --regions "name:L,T,R,B; name2:..." [--range 20]
"""
import argparse
from PIL import Image, ImageChops


def best_shift(figL, realL, box, rng):
    fb = figL.crop(box)
    base_im = ImageChops.difference(fb, realL.crop(box))
    base = sum(base_im.getdata()) / (fb.width * fb.height)
    best = (base, 0, 0)
    for dy in range(-rng, rng + 1):
        for dx in range(-rng, rng + 1):
            rb = realL.crop((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
            d = ImageChops.difference(fb, rb)
            m = sum(d.getdata()) / (fb.width * fb.height)
            if m < best[0]:
                best = (m, dx, dy)
    return base, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("figma"); ap.add_argument("real")
    ap.add_argument("--grid", default="6,4", help="cols,rows")
    ap.add_argument("--regions", default=None, help="'name:L,T,R,B; ...' (있으면 grid 무시)")
    ap.add_argument("--range", type=int, default=20, help="시프트 탐색 ±px")
    ap.add_argument("--thr", type=int, default=4, help="드리프트 보고 임계 px")
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

    print(f"# align_probe  range=±{a.range}px  thr={a.thr}px")
    flagged = []
    for name, box in boxes:
        base, (m, dx, dy) = best_shift(figL, realL, box, a.range)
        drift = max(abs(dx), abs(dy))
        tag = ""
        if drift >= a.thr and (base - m) > 1.0:
            tag = "  <-- DRIFT (블록 위치 — padding/offset/gap/letterSpacing 확인)"
            flagged.append((name, dx, dy, base, m))
        print(f"{name:>10} box={box} MAE@0={base:5.2f} best={m:5.2f}@dx{dx:+d},dy{dy:+d}{tag}")
    print(f"\n# drift 후보 {len(flagged)}개" + ("" if flagged else " — per-block 정렬 OK"))


if __name__ == "__main__":
    main()
