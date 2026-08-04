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
from statistics import median

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
    # argparse 가 help 를 %-포맷하므로 리터럴 % 는 %% 로 써야 한다 (안 하면 --help 가 ValueError 로 죽는다).
    ap.add_argument("--thr", type=float, default=0.12, help="width/coverage 비율 보고 임계 (0.12 = ±12%%)")
    ap.add_argument("--sys-thr", type=float, default=0.005,
                    help="전역 폭 편차 임계 — median width_ratio 가 1 에서 이만큼 벗어나고 방향이 일치하면 "
                         "letterSpacing 선언 대조를 지시 (0.005 = ±0.5%%)")
    ap.add_argument("--outlier-thr", type=float, default=0.03,
                    help="국소 이상치 임계 — median 대비 이만큼 벗어난 영역 (0.03 = ±3%%)")
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

    print(f"# glyph_probe  thr=±{a.thr:.0%}  ink_delta={a.ink}  "
          f"sys=±{a.sys_thr:.1%}  outlier=±{a.outlier_thr:.1%}")
    flagged = []
    rows = []
    for name, box in boxes:
        f = ink_stats(figL, box, a.ink, a.mode)
        r = ink_stats(realL, box, a.ink, a.mode)
        if not f or not r or f["ink"] < 20 or r["ink"] < 20:
            continue  # 텍스트 거의 없는 영역 skip
        wr = r["bbox_w"] / max(1, f["bbox_w"])
        cr = r["coverage"] / max(1e-6, f["coverage"])
        rows.append((name, box, wr, cr))

    # 개별 임계(±thr)는 **큰** 오차만 잡는다. 실측에서 letterSpacing -0.5% 는 width_ratio 0.988(1.2%),
    # 한글 줄바꿈 차이는 1.052(5.2%) 로 나와 둘 다 ±12% 를 통과했다. 그래서 아래 두 축을 함께 본다.
    med_wr = median([w for _, _, w, _ in rows]) if rows else 1.0
    for name, box, wr, cr in rows:
        tag = ""
        if cr > 1 + a.thr:
            tag = "  <-- WEIGHT (real 더 굵음 — faux-bold 의심: 가변폰트 weight 인스턴스 명시 등록)"
            flagged.append((name, "weight", round(cr, 3)))
        elif abs(wr - 1) > a.thr:
            tag = "  <-- WIDTH (advance 차 — letterSpacing/폰트 advance figma 직독)"
            flagged.append((name, "width", round(wr, 3)))
        elif abs(wr - med_wr) > a.outlier_thr:
            # 다른 텍스트는 맞는데 이 영역만 다르다 → 폰트 전역 문제가 아니라 이 노드의 줄바꿈/폭 문제.
            tag = f"  <-- OUTLIER (median {med_wr:.3f} 대비 {wr - med_wr:+.3f} — 줄바꿈 위치·폭 확인)"
            flagged.append((name, "outlier", round(wr, 3)))
        print(f"{name:>10} box={box} width_ratio={wr:.3f} coverage_ratio={cr:.3f}{tag}")

    # 전역 편차: 모든 텍스트가 **같은 방향으로** 조금씩 좁거나 넓으면 개별 임계로는 영원히 안 걸린다.
    # 이건 노드별 오차가 아니라 스타일 선언(letterSpacing/tracking) 문제라서, 픽셀이 아니라 **선언값**을
    # 대조해야 한다 — 그래서 FAIL 이 아니라 "선언 대조하라"는 지시로 낸다.
    # 방향 일치는 **편차가 있는 영역들 사이에서만** 센다. 글자 수가 적은 영역(`9:41`, `←`)은 advance 차가
    # 누적되지 않아 width_ratio 가 정확히 1.000 으로 나오는데, 그걸 분모에 넣으면 진짜 전역 편차가
    # 희석돼 안 걸린다(실측: letterSpacing -0.5% 화면에서 6/9 가 되어 80% 미달).
    deviating = [w for _, _, w, _ in rows if abs(w - 1) > a.sys_thr]
    if len(rows) >= 4 and len(deviating) >= 3 and abs(med_wr - 1) > a.sys_thr:
        side = sum(1 for w in deviating if (w < 1) == (med_wr < 1))
        if side >= 0.8 * len(deviating):
            narrow = "좁다" if med_wr < 1 else "넓다"
            print(f"\n# ⚠️ 전역 폭 편차 — 편차가 있는 텍스트 {side}/{len(deviating)} 개가 같은 방향으로 {narrow} "
                  f"(median width_ratio {med_wr:.3f}).")
            print("#    개별 임계로는 안 걸리는 크기다. 픽셀이 아니라 **선언값**을 대조할 것 — "
                  "Figma REST `style.letterSpacing`(노드별) vs 코드의 letterSpacing/tracking.")
            flagged.append(("<전역>", "systematic", round(med_wr, 3)))
    print(f"\n# 글리프 폭/굵기 후보 {len(flagged)}개" + ("" if flagged else " — glyph 정합 OK"))


if __name__ == "__main__":
    main()
