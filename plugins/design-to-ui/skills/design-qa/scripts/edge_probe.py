#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 엣지·full-bleed probe — 얇은 선/보더가 **어디서 시작해 어디서 끝나는지**를 좌표로 대조.

이 probe 가 따로 있는 이유는 면적 평균 계열 지표가 이 오차를 **원리적으로** 못 보기 때문이다(실측):

  - `overlay` 의 `pct_over_32` 는 픽셀 diff 32 초과만 센다. 흰 배경(255) 위 `#E5E5E5`(229) 선의 diff 는
    **26** 이라 선의 굵기·길이와 무관하게 `pct_over_32` 는 항상 `0.00` 이다.
  - 같은 오차의 12×8 셀 평균은 `0.14` 로 텍스트 화면 floor 밴드(≈3.8)의 1/27 이다. 실제 캡처에는 AA 잔차가
    있어 **구분선 셀이 `suspect_regions` top-N 에서 밀려난다** → 사람이 볼 `cmp_*.png` 가 아예 안 생긴다.
  - `align_probe` 는 평행이동만 본다. 선의 *길이*가 줄어든 것은 어떤 (dx,dy) 로도 MAE 가 개선되지 않아
    `per-block 정렬 OK` 가 나온다.

그래서 평균이 아니라 **ink 시작·끝 좌표를 절대 비교**한다. 좌표 비교는 AA 에 사실상 면역이다
(실측: GaussianBlur 0.4/0.8/1.2 에서 시작·끝 x 차이 0px, 극단 2.0 에서도 0px).

**ink 판정이 다른 probe 와 다르다 — 절대 임계가 아니라 배경↔선의 중간 레벨이다.** 텍스트 probe 의 기본
`--ink 40`(배경보다 40 이상 어두운 픽셀)은 옅은 구분선(배경 대비 **26**)을 ink 로 아예 인식하지 못한다 —
그 임계를 그대로 쓰면 검사가 공회전한다. 이 probe 는 박스의 배경·최암 레벨을 읽어 **그 중간에서** 자르므로
선 색이 얼마나 옅은지와 무관하게 잡히고, 대칭 AA 는 중간 레벨 교차점을 옮기지 않아 **AA 에도 면역**이다.
`--min-contrast` 는 "이 정도 대비도 없으면 선이 없다고 본다"는 하한(기본 8)일 뿐 감도 조절 손잡이가 아니다.

region 은 `enumerate_regions.py --emit edge` 로 **기계 열거**한다(면적 평균 top-N 은 얇은 선을 후보로
올리지 못하므로 손으로 만들면 매 세션 빠진다).

usage:
  python3 edge_probe.py <figma.png> <real.png> --regions "divider:0,830,1080,850"
  python3 edge_probe.py <figma.png> <real.png> --regions "$(python3 enumerate_regions.py meta.json --scale 3 --emit edge)"
  python3 edge_probe.py <figma.png> <real.png> --regions "..." --thr 2 --scale 3 --mode dark
"""
import argparse
import sys

from PIL import Image

# 좌표 임계(px). AA 내성 실측이 0px(극단 blur 2.0 포함)이라 2px 면 오탐 없이 여유가 있다.
DEFAULT_THR_PX = 2
# "선이 있다"고 볼 최소 대비. 감도 손잡이가 아니라 하한 — 판정은 배경↔선의 중간 레벨에서 한다.
DEFAULT_MIN_CONTRAST = 8


def ink_extent(imgL, box, min_contrast, axis, mode="dark"):
    """box 안 ink 픽셀의 축 방향 시작·끝(박스 로컬 좌표) + ink 픽셀 수.

    axis='h' 면 열(x) 범위, 'v' 면 행(y) 범위를 잰다. 선이 sub-pixel 로 흔들려도 박스 전체의 ink 열/행
    합집합을 쓰므로 행 하나를 고르는 방식보다 안정적이다.

    판정 레벨은 배경과 선 색의 **중간**이다 — 옅은 선(대비 26)도 잡히고, 대칭 AA 는 중간 레벨 교차점을
    옮기지 않으므로 blur 강도에 흔들리지 않는다(실측: blur 0.4/1.2/2.0 에서 시작·끝 0px 변화).
    """
    crop = imgL.crop(box)
    w, h = crop.size
    px = list(crop.getdata())
    if not px:
        return None
    srt = sorted(px)
    if mode == "light":                      # 어두운 배경 위 옅은/흰 선 (다크 모드)
        bg = srt[int(len(px) * 0.1)]
        peak = srt[min(len(srt) - 1, int(len(px) * 0.99))]
        contrast = peak - bg
        thr = (bg + peak) / 2.0
        is_ink = lambda v: v > thr
    else:                                    # 밝은 배경 위 어두운/옅은 회색 선
        bg = srt[int(len(px) * 0.9)]
        peak = srt[max(0, int(len(px) * 0.01))]
        contrast = bg - peak
        thr = (bg + peak) / 2.0
        is_ink = lambda v: v < thr
    if contrast < min_contrast:
        return {"ink": 0, "start": None, "end": None, "bg": bg, "thr": round(thr, 1), "contrast": contrast}
    idx = set()
    n = 0
    for i, v in enumerate(px):
        if is_ink(v):
            n += 1
            idx.add(i % w if axis == "h" else i // w)
    if not idx:
        return {"ink": 0, "start": None, "end": None, "bg": bg, "thr": round(thr, 1), "contrast": contrast}
    return {"ink": n, "start": min(idx), "end": max(idx), "bg": bg,
            "thr": round(thr, 1), "contrast": contrast}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("figma")
    ap.add_argument("real")
    ap.add_argument("--regions", required=True, help="'name:L,T,R,B; ...' (enumerate_regions --emit edge)")
    ap.add_argument("--thr", type=float, default=DEFAULT_THR_PX, help="시작/끝 좌표 임계 px (기본 2)")
    ap.add_argument("--min-contrast", type=int, default=DEFAULT_MIN_CONTRAST,
                    help="'선이 있다'고 볼 최소 대비 (기본 8). 판정 레벨은 배경↔선 중간 — 감도 손잡이 아님")
    ap.add_argument("--scale", type=float, default=None, help="px per dp — 주면 dp 로도 리포트")
    ap.add_argument("--mode", choices=["dark", "light"], default="dark",
                    help="선 극성: dark=밝은배경 위 어두운선, light=어두운배경 위 옅은/흰선(다크 모드)")
    ap.add_argument("--axis", choices=["auto", "h", "v"], default="auto",
                    help="측정 축 (기본 auto: 박스가 가로로 길면 h)")
    a = ap.parse_args()

    figL = Image.open(a.figma).convert("L")
    realL = Image.open(a.real).convert("L")

    print(f"# edge_probe thr=±{a.thr:g}px level=mid(bg,line) min_contrast={a.min_contrast} mode={a.mode}"
          + (f" scale={a.scale:g}px/dp" if a.scale else ""))
    print("#   좌표 비교 — 면적 평균(pct_over_32/mean_diff)이 원리적으로 못 보는 카테고리")
    flagged, checked, skipped = [], 0, []
    for part in a.regions.split(";"):
        part = part.strip()
        if not part:
            continue
        name, coords = part.split(":")
        name = name.strip()
        box = tuple(int(v) for v in coords.split(","))
        axis = a.axis
        if axis == "auto":
            axis = "h" if (box[2] - box[0]) >= (box[3] - box[1]) else "v"
        f = ink_extent(figL, box, a.min_contrast, axis, a.mode)
        r = ink_extent(realL, box, a.min_contrast, axis, a.mode)
        if not f or not r or f["ink"] == 0:
            # figma 쪽에 ink 가 없으면 임계나 박스가 틀린 것 — 조용히 통과시키지 않는다.
            skipped.append(name)
            print(f"{name:>14} box={box} axis={axis}  <-- SKIP: figma 에 선이 없음 "
                  f"(bg={f['bg'] if f else '?'} contrast={f.get('contrast') if f else '?'} "
                  f"— 박스가 선을 벗어났거나 --mode 가 반대일 수 있음)")
            continue
        checked += 1
        if r["ink"] == 0:
            flagged.append((name, "missing"))
            print(f"{name:>14} box={box} axis={axis}  figma=({f['start']},{f['end']}) real=(없음)"
                  f"  <-- MISSING: real 에 선이 없다 (미구현/색 누락)")
            continue
        ds, de = r["start"] - f["start"], r["end"] - f["end"]
        # 박스 로컬 → 절대 좌표로 찍어야 사람이 코드와 바로 대조할 수 있다.
        off = box[0] if axis == "h" else box[1]
        line = (f"{name:>14} box={box} axis={axis} "
                f"figma=({off + f['start']},{off + f['end']}) real=({off + r['start']},{off + r['end']}) "
                f"Δstart={ds:+d} Δend={de:+d}")
        if a.scale:
            line += f" ({ds / a.scale:+.2f}dp / {de / a.scale:+.2f}dp)"
        tag = ""
        if abs(ds) > a.thr or abs(de) > a.thr:
            flagged.append((name, f"Δstart={ds:+d} Δend={de:+d}"))
            # 좌우가 서로 안쪽으로 같은 만큼 들어왔으면 부모/자식 수평 패딩이 선에 걸린 것.
            if ds > a.thr and de < -a.thr:
                why = "선이 수평 패딩 안쪽에 있음 — 선을 padding 밖으로 빼거나 음수 마진/fillMaxWidth 로 full-bleed"
            elif abs(ds) > a.thr and abs(de) > a.thr and (ds > 0) == (de > 0):
                why = "선 전체가 평행이동 — 위치 선언값(offset/시작 좌표) 직독 교체"
            else:
                why = "선 길이 불일치 — 한쪽 끝의 패딩/제약 확인"
            tag = f"  <-- EDGE MISMATCH ({why})"
        print(line + tag)

    print(f"\n# 엣지 후보 {len(flagged)}개 / 검사 {checked}개"
          + (f" / SKIP {len(skipped)}개 {skipped}" if skipped else "")
          + ("" if flagged else " — 엣지·full-bleed OK"))
    # ledger 커버리지 근거로 쓸 수 있게 검사 수를 기계 판독 가능한 한 줄로 남긴다.
    print(f"# coverage probed={checked} skipped={len(skipped)}")
    if skipped:
        sys.exit(2)                          # 검사 못한 행을 '통과'로 오해하지 않게 비정상 종료


if __name__ == "__main__":
    main()
