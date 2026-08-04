#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 글리프 정체성 probe — 아이콘이 figma와 '같은 그림'인지 형태로 대조.

overlay 평균 diff는 '틀린 글리프'(십자 vs 화살표)와 '약간 어긋남'을 못 가른다. 이 스크립트는 이미 정렬된
figma.png|real.png에서 같은 아이콘 bbox를 떼어, 위치·크기를 정규화한 뒤 ink 마스크의 IoU(겹침)를 잰다.

⚠️⚠️ **IoU 는 크기를 보지 않는다 — 설계상 지운다.** `norm_cells()` 가 ink bbox 를 32×32 그리드로 정규화하므로
위치·크기 차가 제거되고 *모양만* 남는다. 그래서 **아이콘이 10% 작아도 `IoU=1.00` 이 나온다**(실측: figma 20dp
vs real 18dp → IoU 1.00, `glyph_probe` 도 `width_ratio 0.902` 로 ±12% 임계 미달이라 통과). 크기 검사는
**`--size-check` 로 따로 켜야 한다** — 이 probe 의 IoU 통과를 "아이콘 정합"으로 읽지 말 것. `--size-check`
는 정규화 **전** 원본 ink bbox 를 dp 절대값으로 비교한다(비율이 아니라 절대값이어야 10% 오차가 걸린다).
ledger 의 `glyph_map` 행(모양)과 `asset_size` 행(크기)은 **서로 다른 행**이고, 이 옵션이 후자의 instrument 다.

⚠️ box에 옆 글자(예 아이콘 옆 "°")가 섞이면 IoU가 잘못 떨어져 false-positive가 난다(실측). 그래서 영역에서
**가장 큰 8-연결 ink 성분(=아이콘 본체)의 bbox로 자동 타이트닝**한 뒤 비교한다 — 떨어져 있는 이웃 글자는
배제된다. 그래도 텍스트 인접 소형 글리프는 경계 케이스가 있으니, **flag는 단정이 아니라 "직접 크롭 확인 후
재export"** 신호로 쓴다(올바른 글리프를 needless 재export하지 말 것).

큰 정체성 오류(십자↔화살표, 화살표↔캐럿)는 결정적으로 잡힌다. 비슷한 두 글리프는 임계 근처라 갈릴 수 있다.

region 은 `enumerate_regions.py --emit glyph` 로 **기계 열거**한다 — `overlay` 의 면적 평균 top-N 을 보고
손으로 만들면 작은 아이콘이 후보에 올라오지 않아 세션마다 커버리지가 달라진다.

usage:
  python3 glyph_id_probe.py <figma.png> <real.png> --regions "loc:L,T,R,B; close:L,T,R,B" [--thr 0.6] [--ink 40]
  python3 glyph_id_probe.py <figma.png> <real.png> --regions "..." --size-check --scale 3 [--size-thr-dp 1.0]
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


def half_level_pts(imgL, box):
    """배경↔ink **중간 레벨**에서 ink 판정 — 크기 측정용(AA 면역).

    절대 delta(`ink_pts`)로 크기를 재면 AA 가 번진 만큼 bbox 가 커진다(실측: GaussianBlur 2.0 에서
    61px→65px = +1.33dp 오탐). 대칭 블러는 배경과 ink 의 **중간 밝기 교차점을 옮기지 않으므로**,
    중간 레벨로 자르면 AA 강도와 무관하게 같은 크기가 나온다(실측: blur 0.4/1.2/2.0 전부 61px).
    """
    crop = imgL.crop(box)
    px = list(crop.getdata())
    w = crop.size[0]
    if not px:
        return []
    srt = sorted(px)
    bg = srt[int(len(px) * 0.9)]
    mn = srt[max(0, int(len(px) * 0.01))]          # 1퍼센타일 — 단발 노이즈에 안 끌림
    if bg - mn < 8:                                 # 대비가 거의 없으면 ink 없음으로 본다
        return []
    thr = (bg + mn) / 2.0
    return [(i % w, i // w) for i, v in enumerate(px) if v < thr]


def largest_component_bbox_tight(pts):
    """가장 큰 8-연결 성분(아이콘 본체)의 **타이트** bbox — margin 확장 없음.

    `--size-check` 가 쓰는 값이다. 크기를 재려면 margin 이 섞이면 안 된다(margin_frac 은 bbox 크기에
    비례해 붙으므로 크기 오차를 그만큼 희석한다).
    """
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
    return (mnx, mny, mxx, mxy)


def largest_component_bbox(pts, margin_frac=0.25):
    """타이트 bbox를 margin 확장해 반환 — IoU 정규화용(떨어진 이웃 글자 배제)."""
    mnx, mny, mxx, mxy = largest_component_bbox_tight(pts)
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
    ap.add_argument("--size-check", action="store_true",
                    help="정규화 전 원본 ink bbox 크기도 비교 (IoU 는 크기를 지운다 — ledger 의 asset_size 행)")
    ap.add_argument("--scale", type=float, default=None, help="px per dp — size-check 를 dp 로 판정")
    ap.add_argument("--size-thr-dp", type=float, default=1.0,
                    help="크기 임계 dp (기본 ±1dp — AA 내성 실측 0.67dp 보다 큼)")
    ap.add_argument("--size-thr-px", type=float, default=None,
                    help="--scale 없을 때의 크기 임계 px (기본: size-thr-dp × 3)")
    a = ap.parse_args()

    figL = Image.open(a.figma).convert("L")
    realL = Image.open(a.real).convert("L")
    print(f"# glyph_id_probe IoU_thr={a.thr} ink={a.ink}  (flag=크롭 확인 후 재export, 단정 아님)")
    if a.size_check:
        unit = f"±{a.size_thr_dp:g}dp @{a.scale:g}px/dp" if a.scale \
            else f"±{a.size_thr_px if a.size_thr_px is not None else a.size_thr_dp * 3:g}px (--scale 미지정)"
        print(f"# size-check ON  thr={unit} — IoU 는 크기를 정규화로 지우므로 이 행이 크기를 본다")
    else:
        print("# size-check OFF — IoU 통과는 '모양이 같다'는 뜻일 뿐 크기 정합이 아니다 (--size-check 로 크기 검사)")
    flagged, size_flagged, checked = [], [], 0
    for part in a.regions.split(";"):
        part = part.strip()
        if not part:
            continue
        name, coords = part.split(":")
        name = name.strip()
        box = tuple(int(v) for v in coords.split(","))
        fp = ink_pts(figL, box, a.ink)
        rp = ink_pts(realL, box, a.ink)
        # ⚠️ 절대 임계(--ink)는 **옅은 아이콘을 못 본다.** 실측: 튜토리얼 앱의 체크 아이콘은 카드 배경(245)
        # 위 230 이라 대비가 15 뿐이고 --ink 40 으로는 0px → 전 region 이 skip 되어 검사가 공회전했다
        # (그때 coverage probed=0 이라 종료 게이트가 막아주긴 하지만, 검사 자체가 안 된 것이다).
        # 그래서 부족하면 배경↔ink 중간 레벨로 재시도한다 — 대비와 무관하게 잡힌다.
        if len(fp) < 10 or len(rp) < 10:
            fp2, rp2 = half_level_pts(figL, box), half_level_pts(realL, box)
            if len(fp2) >= 10 and len(rp2) >= 10:
                fp, rp = fp2, rp2
                print(f"{name:>10} (저대비 — 중간 레벨로 재측정)")
            else:
                print(f"{name:>10} (ink 부족 — skip: 박스에 글리프가 없거나 대비 없음)")
                continue
        checked += 1
        # 각자 자기 본체로 타이트닝 (이웃 글자 배제). 크기는 AA 면역인 중간 레벨로 따로 잰다.
        fsp, rsp = half_level_pts(figL, box), half_level_pts(realL, box)
        ftb = largest_component_bbox_tight(fsp or fp)
        rtb = largest_component_bbox_tight(rsp or rp)
        fc = norm_cells(fp, largest_component_bbox(fp))
        rc = norm_cells(rp, largest_component_bbox(rp))
        iou = len(fc & rc) / (len(fc | rc) or 1)
        tag = "" if iou >= a.thr else "  <-- SHAPE MISMATCH? (크롭 확인 후, 맞으면 올바른 figma 노드로 재export)"
        if iou < a.thr:
            flagged.append(name)
        print(f"{name:>10} box={box} IoU={iou:.2f}{tag}")
        if not a.size_check:
            continue
        # 정규화 **전** 타이트 bbox 크기 — 절대 비교(비율이 아니라 절대값이어야 10% 오차가 걸린다).
        fw, fh = ftb[2] - ftb[0] + 1, ftb[3] - ftb[1] + 1
        rw, rh = rtb[2] - rtb[0] + 1, rtb[3] - rtb[1] + 1
        dw, dh = rw - fw, rh - fh
        if a.scale:
            thr, u = a.size_thr_dp, "dp"
            vals = (fw / a.scale, fh / a.scale, rw / a.scale, rh / a.scale, dw / a.scale, dh / a.scale)
        else:
            thr = a.size_thr_px if a.size_thr_px is not None else a.size_thr_dp * 3
            u = "px"
            vals = (fw, fh, rw, rh, dw, dh)
        fwv, fhv, rwv, rhv, dwv, dhv = vals
        over = abs(dwv) > thr or abs(dhv) > thr
        stag = ""
        if over:
            size_flagged.append((name, round(dwv, 2), round(dhv, 2)))
            stag = ("  <-- ASSET SIZE (figma 선언 크기로 교체 — 에셋 size 지정/컨테이너 제약 확인. "
                    "IoU 가 1.00 이어도 크기는 틀릴 수 있다)")
        print(f"{'':>10}   size figma={fwv:.2f}x{fhv:.2f}{u} real={rwv:.2f}x{rhv:.2f}{u} "
              f"Δ={dwv:+.2f}x{dhv:+.2f}{u} ratio={rw / max(1, fw):.3f}{stag}")
    print(f"\n# 형태 의심 {len(flagged)}개 (크롭 확인 필요)" + ("" if flagged else " — 글리프 정체성 OK"))
    if a.size_check:
        print(f"# 크기 의심 {len(size_flagged)}개" + ("" if size_flagged else " — 에셋 크기 OK")
              + (f" {size_flagged}" if size_flagged else ""))
    # ledger 커버리지 근거 — 열거 수와 대조한다(ledger_gate coverage 검사).
    print(f"# coverage probed={checked}")


if __name__ == "__main__":
    main()
