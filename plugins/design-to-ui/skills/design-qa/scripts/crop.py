#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: exact-crop — 풀스크린 캡처에서 대상 창 영역만 정확히 잘라낸다.

exact-crop 이 이 검증 루프의 핵심이다. 풀스크린을 좌표 추측으로 자르면 ~15px 오프셋
artifact 로 "틀어짐" 오판이 난다. 모드:

  frame  — 일반/Wide 창. `dumpsys window windows` 에서 대상 창 frame 을 crop 박스로 쓴다
           (창이 실제 디스플레이 좌표를 줄 때). 구 포맷 `frame=[L,T,R,B]`(한 줄)·현행 포맷
           `Window{...pkg/activity}:` 뒤 `frame=[L,T][R,B]`(멀티라인) 모두 지원. 원점 (0,0)이면
           임베디드 로컬좌표 의심 경고(그 경우 auto 권장).

  auto   — content 기반 자동 정렬. figma 기준 래스터(그 노드 전체 렌더)를 템플릿으로
           풀스크린 캡처 안에서 위치를 coarse→fine 엣지-SAD 매칭해 crop 박스를 산출한다.
           **임베디드/멀티윈도 호스트**(dumpsys 가 로컬좌표 (0,0) 만 주는 경우)의 일반 해법 —
           dumpsys 좌표·수동 박스·기기별 상수 없이 동작한다. 프레임 전체를 단일 (dx,dy) 로만
           평행이동해 맞추므로, 카드·패널 외곽 같은 안정 구조가 정렬을 지배하고 요소별 오차는
           그대로 남아 판정에 드러난다(오차를 숨기지 않는다).

  anchor — 임베드 TaskView 등. Figma 의 고정 요소(닫기 X 버튼) 를 앵커로 패널 top-left 를 역산.
               panel_topleft = (X_cap - X_fig_section_relative)

  box    — 디스플레이 절대 crop 박스를 직접 고정(1회 정렬로 확정해 재사용).

`--figma <figma.png>` 를 frame/box/anchor 에 주면 crop 후 **정합 게이트**를 돈다: figma 대비
전역 best (dx,dy) 가 임계(±3px) 초과면 "crop 오프셋 의심" 경고 → auto 재시도를 권한다.

usage:
    python3 crop.py frame  <cap.png> <out.png> --package com.nhn.android.search [--activity MainActivity] [--serial S] [--figma f.png]
    python3 crop.py auto   <cap.png> <figma.png> <out.png> [--search L,T,R,B] [--scales 8,2] [--scale-candidates 1,2,3,1.5,0.5,0.75]
    python3 crop.py anchor <cap.png> <out.png> --cap-anchor 2470,150 --fig-anchor 1620,60 --panel-size 1700,1184 [--figma f.png]
    python3 crop.py box    <cap.png> <out.png> --box 840,96,2540,1280 [--figma f.png]
"""
import argparse
import re
import subprocess
import sys

from PIL import Image, ImageChops, ImageFilter, ImageStat

# crop 후 정합 게이트 임계 (전역 best-shift px). 이보다 크면 crop 박스 오프셋 의심.
GATE_THR_PX = 3
# 게이트 전역 오프셋 탐색 반경 (px). 임계보다 넉넉히 커야 큰 오프셋을 잡는다.
GATE_SEARCH_PX = 40


def _dumpsys_windows(serial: str | None) -> str:
    cmd = ["adb"] + (["-s", serial] if serial else []) + ["shell", "dumpsys", "window", "windows"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


# frame= 값: 구 포맷 `[L,T,R,B]`(콤마 4개) 또는 현행 `[L,T][R,B]`(대괄호 쌍) 둘 다 매칭.
_FRAME_RE = r"frame=\[(\d+),(\d+)(?:,|\]\[)(\d+),(\d+)\]"


def frame_box(package: str, activity: str | None, serial: str | None) -> tuple[int, int, int, int]:
    """dumpsys 에서 대상 창의 frame=[L,T,R,B] 추출. 구/현행 dumpsys 포맷 모두 지원.

    - 구 포맷: `<pkg>/<activity>, frame=[L,T,R,B]` (한 줄).
    - 현행 포맷: `Window{... <pkg>/<activity>}:` 헤더 뒤 별도 `Frames: ... frame=[L,T][R,B]` 줄.
    """
    dump = _dumpsys_windows(serial)
    act = re.escape(activity) if activity else r"[\w.]+"
    win = re.escape(package) + r"/[\w.]*" + act
    # (a) 구 포맷: 같은 줄 "pkg/activity ... , frame=[...]"
    m = re.search(win + r"[^,\n]*,\s*" + _FRAME_RE, dump)
    if not m:
        # (b) 현행 포맷: Window{... pkg/activity}: 헤더 다음의 첫 frame=
        wm = re.search(r"Window\{[^}]*" + win + r"[^}]*\}:", dump)
        if wm:
            m = re.search(_FRAME_RE, dump[wm.end():])
    if not m:
        sys.exit(f"frame 미발견: {package} (activity={activity}). 창이 포그라운드인지 확인.")
    box = tuple(int(x) for x in m.groups())  # type: ignore
    if box[0] == 0 and box[1] == 0:
        print("⚠️  frame 원점 (0,0) — 풀스크린이 아니라 임베디드/멀티윈도 로컬좌표면 화면 좌상단을 "
              "잘못 crop함. 의심되면 `crop.py auto <cap> <figma> <out>` 사용(또는 --figma 게이트로 검산).",
              file=sys.stderr)
    return box


# ── content 기반 자동 정렬 (auto 모드 & 게이트 공용) ───────────────────────────

def _edge(im: Image.Image, scale: int) -> Image.Image:
    """스케일 축소 + 그레이스케일 + 엣지. 색/AA 차이에 강건하게 구조만 남긴다."""
    w, h = im.size
    s = im.resize((max(1, w // scale), max(1, h // scale)))
    return s.convert("L").filter(ImageFilter.FIND_EDGES)


def _sad(a: Image.Image, b: Image.Image) -> float:
    """평균 절대차 (C 레벨)."""
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def _ncc(a: Image.Image, b: Image.Image) -> float:
    """엣지맵 정규화 상관(-1~1). 스케일·밝기 무관 → 스케일 선택 편향 제거.

    raw SAD 는 흐릿하게 확대된(엣지 약한) 템플릿이 flat 영역과 낮은 차이로 스퓨리어스 매칭되는
    편향이 있어, 스케일 후보 비교엔 SAD 대신 이 정규화 상관을 쓴다.
    """
    pa, pb = list(a.getdata()), list(b.getdata())
    n = len(pa)
    if n == 0:
        return 0.0
    ma, mb = sum(pa) / n, sum(pb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(pa, pb))
    da = sum((x - ma) ** 2 for x in pa)
    db = sum((y - mb) ** 2 for y in pb)
    if da <= 0 or db <= 0:
        return 0.0
    return num / ((da * db) ** 0.5)


def _search(cap: Image.Image, fig: Image.Image, scale: int,
            center: tuple[int, int] | None, radius: int,
            region: tuple[int, int, int, int] | None,
            cap_edge: Image.Image | None = None) -> tuple[float, int, int]:
    """스케일 축소 엣지맵에서 fig 템플릿의 best 위치를 SAD 로 찾는다. (score, X, Y) full-res.

    cap_edge: 같은 scale 의 cap 엣지맵을 미리 만들어 넘기면 재계산 생략(후보 루프 최적화).
    """
    caps = cap_edge if cap_edge is not None else _edge(cap, scale)
    figs = _edge(fig, scale)
    tw, th = figs.size
    if center is not None:
        cx, cy = center[0] // scale, center[1] // scale
        xr = range(max(0, cx - radius), min(caps.width - tw, cx + radius) + 1)
        yr = range(max(0, cy - radius), min(caps.height - th, cy + radius) + 1)
    elif region is not None:
        l, t, r, b = (v // scale for v in region)
        xr = range(max(0, l), min(caps.width - tw, max(0, r - tw)) + 1)
        yr = range(max(0, t), min(caps.height - th, max(0, b - th)) + 1)
    else:
        xr = range(0, caps.width - tw + 1)
        yr = range(0, caps.height - th + 1)
    best = (float("inf"), 0, 0)
    for y in yr:
        for x in xr:
            m = _sad(caps.crop((x, y, x + tw, y + th)), figs)
            if m < best[0]:
                best = (m, x * scale, y * scale)
    return best


def auto_box(cap: Image.Image, fig: Image.Image, ds_scales: tuple[int, ...],
             region: tuple[int, int, int, int] | None,
             scale_candidates: tuple[float, ...]) -> tuple[int, int, int, int, float, float]:
    """figma 를 템플릿으로 캡처 내 위치를 coarse→fine 매칭 → crop 박스 (L,T,R,B, scale, score).

    화면 렌더가 figma 원본과 다른 density(픽셀 스케일)로 떠도 잡도록, 후보 스케일마다
    템플릿을 리사이즈해 coarse 매칭한 뒤 최적 스케일에서 translation 을 fine-tune 한다.
    (mdpi 1:1 이면 scale 1.0 이 이긴다. crop 박스 크기는 화면 렌더 스케일을 따르고,
    overlay.py 가 figma 를 그 크기로 resize 하므로 정합에 문제없다.)
    """
    # 스케일별로 SAD 로 best 위치를 찾되, 스케일 간 선택은 정규화 상관(NCC)으로 (편향 제거).
    cds = ds_scales[0]
    caps_e = _edge(cap, cds)
    best = None  # (ncc, s, X, Y)
    for s in scale_candidates:
        tw, th = round(fig.width * s), round(fig.height * s)
        if tw > cap.width or th > cap.height or tw < 8 or th < 8:
            continue
        figS = fig.resize((tw, th))
        _, X, Y = _search(cap, figS, cds, None, 0, region, cap_edge=caps_e)
        figs_e = _edge(figS, cds)
        rx, ry = X // cds, Y // cds
        region_e = caps_e.crop((rx, ry, rx + figs_e.width, ry + figs_e.height))
        ncc = _ncc(region_e, figs_e)
        if best is None or ncc > best[0]:
            best = (ncc, s, X, Y)
    if best is None:
        sys.exit("auto: 매칭 가능한 스케일이 없음 (모든 후보 템플릿이 캡처보다 큼).")
    ncc, s, X, Y = best
    tw, th = round(fig.width * s), round(fig.height * s)
    figS = fig.resize((tw, th))
    score = 0.0
    for ds in ds_scales[1:]:
        score, X, Y = _search(cap, figS, ds, (X, Y), ds_scales[0] // ds + 4, None,
                              cap_edge=_edge(cap, ds))
    return X, Y, X + tw, Y + th, s, score


def global_offset(real: Image.Image, fig: Image.Image) -> tuple[int, int, float, float]:
    """real 대비 figma 를 전역 평행이동해 MAE 최소가 되는 (dx, dy, base_MAE, best_MAE)."""
    if real.size != fig.size:  # 크기 다르면 overlay 가 resize — 여기선 위치만 본다
        fig = fig.resize(real.size)
    scale = 4
    caps, figs = _edge(real, scale), _edge(fig, scale)
    base = _sad(caps, figs)
    best = (base, 0, 0)
    rng = GATE_SEARCH_PX // scale + 1
    for dy in range(-rng, rng + 1):
        for dx in range(-rng, rng + 1):
            m = _sad(caps, ImageChops.offset(figs, dx, dy))
            if m < best[0]:
                best = (m, dx * scale, dy * scale)
    return best[1], best[2], base, best[0]


def gate(out_path: str, figma_path: str) -> bool:
    """crop 후 정합 게이트: figma 대비 전역 오프셋이 임계 초과면 경고. (True=경고)"""
    dx, dy, base, score = global_offset(Image.open(out_path), Image.open(figma_path))
    drift = max(abs(dx), abs(dy))
    warn = drift > GATE_THR_PX and (base - score) > 0.5
    if warn:
        print(f"⚠️  정합 게이트: 전역 오프셋 ~dx{dx:+d},dy{dy:+d} (>{GATE_THR_PX}px) 감지 "
              f"— crop 박스가 어긋났을 수 있음. `crop.py auto <cap> <figma> <out>` 재시도 권장.")
    else:
        print(f"정합 게이트 OK (전역 오프셋 ≤{GATE_THR_PX}px).")
    return warn


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    pf = sub.add_parser("frame")
    pf.add_argument("cap"); pf.add_argument("out")
    pf.add_argument("--package", required=True)
    pf.add_argument("--activity", default=None)
    pf.add_argument("--serial", default=None)
    pf.add_argument("--figma", default=None, help="주면 crop 후 정합 게이트 실행")

    # auto: content 기반 자동 정렬 — 임베디드/멀티윈도 호스트의 일반 해법.
    pa2 = sub.add_parser("auto")
    pa2.add_argument("cap"); pa2.add_argument("figma"); pa2.add_argument("out")
    pa2.add_argument("--search", default=None, help="탐색 제한 영역 'L,T,R,B' (기본 전체)")
    pa2.add_argument("--scales", default="8,2", help="coarse→fine 다운스케일 배율 (기본 8,2)")
    pa2.add_argument("--scale-candidates", default="1,2,3,1.5,0.5,0.75",
                     help="화면 density 대응 템플릿 스케일 후보 (기본 1,2,3,1.5,0.5,0.75)")

    pa = sub.add_parser("anchor")
    pa.add_argument("cap"); pa.add_argument("out")
    pa.add_argument("--cap-anchor", required=True, help="캡처 내 X버튼 center 'x,y'")
    pa.add_argument("--fig-anchor", required=True, help="figma 섹션상대 X버튼 center 'x,y'")
    pa.add_argument("--panel-size", required=True, help="패널 크기 'w,h' (dumpsys mBounds)")
    pa.add_argument("--figma", default=None, help="주면 crop 후 정합 게이트 실행")

    pb = sub.add_parser("box")
    pb.add_argument("cap"); pb.add_argument("out")
    pb.add_argument("--box", required=True, help="디스플레이 절대 'L,T,R,B'")
    pb.add_argument("--figma", default=None, help="주면 crop 후 정합 게이트 실행")

    a = ap.parse_args()
    im = Image.open(a.cap)

    if a.mode == "auto":
        fig = Image.open(a.figma)
        region = tuple(int(v) for v in a.search.split(",")) if a.search else None
        scales = tuple(int(v) for v in a.scales.split(","))
        cand = tuple(float(v) for v in a.scale_candidates.split(","))
        L, T, R, B, s, score = auto_box(im, fig, scales, region, cand)
        box = (max(0, L), max(0, T), min(im.width, R), min(im.height, B))
        im.crop(box).save(a.out)
        print(f"crop auto box={box} scale={s:g} score={score:.3f} -> {a.out} ({box[2]-box[0]}x{box[3]-box[1]})")
        return

    if a.mode == "frame":
        box = frame_box(a.package, a.activity, a.serial)
    elif a.mode == "box":
        box = tuple(int(v) for v in a.box.split(","))
    else:
        cx, cy = (int(v) for v in a.cap_anchor.split(","))
        fx, fy = (int(v) for v in a.fig_anchor.split(","))
        pw, ph = (int(v) for v in a.panel_size.split(","))
        left, top = cx - fx, cy - fy
        box = (left, top, left + pw, top + ph)

    box = (max(0, box[0]), max(0, box[1]), min(im.width, box[2]), min(im.height, box[3]))
    im.crop(box).save(a.out)
    print(f"crop {a.mode} box={box} -> {a.out} ({box[2]-box[0]}x{box[3]-box[1]})")

    if getattr(a, "figma", None):
        gate(a.out, a.figma)


if __name__ == "__main__":
    main()
