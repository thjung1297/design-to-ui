#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: figma ↔ real 오버레이 + mismatch 추정 (검증 rubric).

rubric 레벨 (가챠 변별 축):
  1  blend-only      — 50% 블렌드만. 정렬/오프셋은 보이나 색오차·작은 글리프를 가린다.
  2  blend+heatmap   — difference 절대차 히트맵(증폭) 추가. 누락/색차 영역을 밝게 드러냄.
  3  blend+heatmap+sample — diff 상위 영역을 자동 검출해 figma|real 나란히 크롭 +
                            영역별 대표/최암 픽셀 색을 수치 비교. (collect Step 4 v9.2 rubric)

산출: <outdir>/{figma.png, real.png, blend50.png, diff.png, cmp_*.png, metrics.json}
metrics.json 으로 후보를 객관 랭크, 이미지로 시각 증거.

--blend-only: blend50.png 한 장만 만들고 나머지 산출물(figma/real 복사·diff·cmp·metrics)은
              만들지 않는다. "오버레이만 띄워줘" 식 빠른 검증용. (보정 루프는 full rubric 사용.)

⚠️ **dp 게이트 (`--figma-dp`/`--real-dp`).** 이 스크립트의 `resize_ratio` 는 **픽셀** 비율이다 — Figma 프레임과
캡처 기기의 **dp 논리 크기가 다르면** dp 차이를 density 차이가 상쇄해 픽셀 공간에서는 거의 겹친다(실측:
360dp 프레임 vs 411dp 기기에서 `resize_ratio [1.0, 1.0256]`, crop 정합 게이트 `OK`). 그런데 레이아웃은 dp 로
계산되므로 실제 화면은 다르다(371dp 폭에서 잡힌 줄바꿈은 320dp 줄바꿈으로 되돌릴 수 없다). 그래서 두 dp 를
받아 다르면 **FAIL 로 멈춘다** — 오버레이 자체가 성립하지 않는 상태에서 유령 오차를 세는 것을 막는다
(실측: dp 를 맞추면 `mean_diff 8.55 → 1.45`, `align_probe` 유령 drift 후보 7개 → 0개).

usage:
    python3 overlay.py <figma.png> <real.png> <outdir> --rubric 3 [--grid 12,8] [--top 5]
    python3 overlay.py <figma.png> <real.png> <outdir> --blend-only
    python3 overlay.py <figma.png> <real.png> <outdir> --figma-dp 360x780 --real-dp 360x780
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageChops, ImageOps

# 픽셀 diff 를 "유의미"로 셀 임계. 이 값은 metrics 에 함께 기록한다 — 대비가 이보다 작은 오차
# (예: 흰 배경 255 위 #E5E5E5 구분선 = diff 26)는 pct_over_32 에 **원리적으로** 안 잡힌다.
DIFF_THRESHOLD = 32
# dp 논리 크기 허용 오차. 반정수 dp 프레임을 고려해 0.5dp.
DP_TOL = 0.5


def _amplify(diff: Image.Image) -> Image.Image:
    g = diff.convert("L")
    return ImageOps.autocontrast(g, cutoff=1).convert("RGB")


def _region_color(img: Image.Image, box) -> tuple:
    """영역의 '대표 = 가장 어두운' 픽셀 색 (텍스트/도형 색 비교용)."""
    c = img.crop(box).convert("RGB")
    px = list(c.getdata())
    darkest = min(px, key=lambda p: p[0] + p[1] + p[2])
    n = len(px)
    mean = tuple(round(sum(p[i] for p in px) / n) for i in range(3))
    return {"darkest": list(darkest), "mean": list(mean)}


def _parse_dp(s):
    """'360x780' → (360.0, 780.0). 반정수 dp('375.5x813')도 받는다."""
    try:
        w, h = s.lower().replace("×", "x").split("x")
        return (float(w), float(h))
    except Exception:
        raise argparse.ArgumentTypeError(f"dp 크기는 'WxH' 형식이어야 함 (받은 값: {s!r})")


def _assert_out_not_in(outdir, *inputs):
    """산출물이 입력을 덮어쓰는 것을 막는다.

    `overlay.py f.png r.png .` 처럼 outdir 를 입력 디렉터리로 주면 `figma.png`·`real.png` 를
    덮어써 **입력이 파괴된다**(복구 불가). 이름이 겹치는 경우만 거부한다.
    """
    out = os.path.realpath(outdir)
    for p in inputs:
        if os.path.realpath(os.path.dirname(p) or ".") == out and \
                os.path.basename(p) in ("figma.png", "real.png", "diff.png",
                                        "blend50.png", "metrics.json"):
            sys.exit(f"산출물이 입력을 덮어쓴다: {p} — outdir 를 따로 지정할 것 (outdir={outdir})")


def extent_gate(fig, real, allow_mismatch):
    """두 이미지의 **픽셀 extent** 가 다르면 멈춘다. dp 게이트로는 안 잡히는 자리다.

    ⚠️ dp 게이트는 프레임/기기의 **선언 dp** 를 본다. 그래서 0단계로 dp 를 완벽히 맞춰도, crop 이
    시스템 영역(상태바·제스처바·인디케이터존)을 **서로 다르게 처리하면** 두 이미지의 세로 길이가
    달라지고 dp 게이트는 `ok` 를 준다. iOS 프레임(인디케이터존 34dp 포함) ↔ Android 캡처
    (제스처바 24dp 제외) 대조에서는 거의 항상 발생한다.

    그 상태로 `fig.resize(real.size)` 하면 y 에 비례하는 유령이 생기고, 그 유령이 **진짜 오차를
    상쇄**해서 지표가 정답과 **반상관**이 된다 — 실측(393x852dp figma vs 393x828dp real):

        정합본     mean_diff 10.26   crop 게이트 OK   dp 게이트 ok   resize_ratio [1.0, 0.9718]
        8dp 오차본 mean_diff  8.55   crop 게이트 OK   dp 게이트 ok   resize_ratio [1.0, 0.9718]

    **정합인 쪽이 오차 있는 쪽보다 나쁜 숫자를 냈고 게이트는 전부 초록불이었다.** 그리고 이 잔차는
    어떤 정렬을 골라도 사라지지 않는다(top-align +10dp / bottom-align −34dp / resize +31dp) —
    콘텐츠 영역의 dp 높이가 실제로 다르기 때문이다. 하단 앵커 요소는 오버레이가 아니라
    **dp 절대 probe** 로 판정하고, 비교 가능한 영역만 crop 해서 대조해야 한다.
    """
    if fig.size == real.size:
        return {"verdict": "ok", "size": list(fig.size)}
    info = {"verdict": "mismatch", "figma_px": list(fig.size), "real_px": list(real.size)}
    msg = (f"extent 게이트 FAIL — figma {fig.width}x{fig.height}px vs "
           f"real {real.width}x{real.height}px\n"
           "  두 이미지 크기가 다르면 resize 가 차이를 흡수하고, 그 유령이 진짜 오차를 상쇄해\n"
           "  지표가 정답과 **반상관**이 된다(실측: 정합본 10.26 vs 8dp 오차본 8.55, 게이트는 초록불).\n"
           "  → crop 을 같은 기준면으로 다시 잡거나(양쪽 다 시스템 영역 제외), 캡처를 다시 할 것.\n"
           "  → 세로 길이 차가 시스템 영역 높이차에서 온 것이면 **어떤 정렬로도 잔차가 남는다.**\n"
           "     하단 앵커 요소는 dp 절대 probe 로 판정하고, 비교 가능한 상단 영역만 crop 해 대조한다.")
    if allow_mismatch:
        print("경고: " + msg)
        print("  (--allow-extent-mismatch 로 강행 중 — 이 실행의 오차 순위는 정답과 반대일 수 있다)")
        info["verdict"] = "mismatch-forced"
        return info
    sys.exit(msg)


def resize_gate(resize_ratio, allow_mismatch):
    """양축 비균일 배율은 판정을 왜곡한다 — 주석이 아니라 게이트로 막는다.

    기존에는 `# 1.0 에서 벗어날수록 패널/프레임 불일치(환경 아티팩트)` 주석만 있었다. 실측에서
    `[1.0, 0.9718]` 하나가 mean_diff 순위를 뒤집었으므로 경고를 넘어 정지 사유로 올린다.
    """
    rx, ry = resize_ratio
    ok = abs(rx - ry) <= 0.001
    if ok:
        return {"verdict": "ok", "ratio": [rx, ry]}
    info = {"verdict": "non-uniform", "ratio": [rx, ry]}
    msg = (f"resize 게이트 FAIL — 축별 배율이 다르다 ({rx:g} vs {ry:g}).\n"
           "  비균일 배율은 한 축의 오차를 늘리고 다른 축의 오차를 지운다. 판정 전에 crop/캡처를 고칠 것.")
    if allow_mismatch:
        print("경고: " + msg)
        info["verdict"] = "non-uniform-forced"
        return info
    sys.exit(msg)


def dp_gate(figma_dp, real_dp, allow_mismatch):
    """Figma 프레임 dp vs 캡처 대상 dp — 다르면 오버레이가 성립하지 않으므로 멈춘다."""
    dw, dh = real_dp[0] - figma_dp[0], real_dp[1] - figma_dp[1]
    ok = abs(dw) <= DP_TOL and abs(dh) <= DP_TOL
    info = {
        "figma_dp": list(figma_dp), "real_dp": list(real_dp),
        "delta_dp": [round(dw, 2), round(dh, 2)], "tol_dp": DP_TOL,
        "verdict": "ok" if ok else "mismatch",
    }
    if ok:
        print(f"dp 게이트 OK — figma {figma_dp[0]:g}x{figma_dp[1]:g}dp == real {real_dp[0]:g}x{real_dp[1]:g}dp")
        return info
    msg = (f"dp 게이트 FAIL — figma {figma_dp[0]:g}x{figma_dp[1]:g}dp vs real "
           f"{real_dp[0]:g}x{real_dp[1]:g}dp (Δ {dw:+g}x{dh:+g}dp)\n"
           "  dp 가 다르면 레이아웃이 **다르게 계산**된다(줄바꿈·wrap·분포). 배율로 되돌릴 수 없고,\n"
           "  픽셀 공간에서는 density 가 상쇄해 거의 겹치므로 resize_ratio·crop 정합 게이트는 **통과해버린다**.\n"
           "  → 캡처 전에 뷰포트를 정규화할 것 (SKILL 워크플로우 0단계):\n"
           "     Android: scripts/viewport.py apply <W>x<H>  (wm size + wm density 를 함께 설정)\n"
           "     iOS: 프레임과 같은 pt 크기의 시뮬레이터 기종 / Web: Playwright viewport\n"
           "  맞출 수 없으면 중단하고 사용자에게 알린다 — 오버레이 자체가 성립하지 않는다.")
    if allow_mismatch:
        print("경고: " + msg)
        print("  (--allow-dp-mismatch 로 강행 중 — 이 실행의 오차 목록은 유령일 수 있다)")
        info["verdict"] = "mismatch-forced"
        return info
    sys.exit(msg)


def _load_figma(path, bg):
    """Figma export 를 불투명하게 만든다 + 투명했던 픽셀 마스크를 함께 반환.

    ⚠️ Figma 프레임은 보통 **라운드 코너**라 export PNG 의 코너가 **투명**하다. 그냥 `convert("RGB")` 하면
    투명이 **검정(0,0,0)** 이 되어 실제 화면(예: 배경 244,245,247)과 diff 가 ~245 씩 난다 — `max_diff` 가
    전부 이 아티팩트로 채워지고(실측 245) `pct_over_32`·코너 셀도 오염된다. 그래서 real 의 배경색으로
    합성하고, 원래 투명했던 픽셀은 **수치 통계에서 제외**한다(설계 정보가 없는 픽셀이다).
    """
    im = Image.open(path)
    if im.mode not in ("RGBA", "LA", "P"):
        return im.convert("RGB"), None
    im = im.convert("RGBA")
    alpha = im.getchannel("A")
    lo, _ = alpha.getextrema()
    if lo == 255:
        return im.convert("RGB"), None
    flat = Image.new("RGB", im.size, bg)
    flat.paste(im, (0, 0), im)
    # 완전 불투명이 아닌 픽셀 = 제외 대상 (0=제외, 255=집계)
    mask = alpha.point(lambda v: 255 if v == 255 else 0)
    return flat, mask


def _bg_color(real):
    """real 캡처의 배경색 추정 — 네 코너의 중앙값. 합성 배경으로 쓴다."""
    w, h = real.size
    pts = [real.getpixel(p) for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
    return tuple(sorted(c[i] for c in pts)[len(pts) // 2] for i in range(3))


def overlay(figma_path, real_path, outdir, rubric, grid, top, blend_only=False,
            figma_dp=None, real_dp=None, allow_dp_mismatch=False,
            allow_extent_mismatch=False):
    _assert_out_not_in(outdir, figma_path, real_path)
    os.makedirs(outdir, exist_ok=True)
    gate_info = None
    if figma_dp and real_dp:
        gate_info = dp_gate(figma_dp, real_dp, allow_dp_mismatch)
    elif figma_dp or real_dp:
        sys.exit("dp 게이트: --figma-dp 와 --real-dp 는 함께 줘야 한다 (한쪽만으로는 비교 불가)")
    real = Image.open(real_path).convert("RGB")
    fig, fig_mask = _load_figma(figma_path, _bg_color(real))
    extent_info = extent_gate(fig, real, allow_extent_mismatch)
    resize_ratio = (round(real.width / fig.width, 4), round(real.height / fig.height, 4))
    resize_info = resize_gate(resize_ratio, allow_extent_mismatch)
    fig_r = fig.resize(real.size)
    mask_r = fig_mask.resize(real.size, Image.NEAREST) if fig_mask is not None else None

    # --blend-only: blend50.png 한 장만. 빠른 오버레이 표시용.
    if blend_only:
        blend = Image.blend(fig_r, real, 0.5)
        out = f"{outdir}/blend50.png"
        blend.save(out)
        print(out)
        return

    fig_r.save(f"{outdir}/figma.png")
    real.save(f"{outdir}/real.png")

    metrics = {
        "real_size": list(real.size),
        "figma_native_size": list(fig.size),
        # 픽셀 비율이다. 양축 균일이어도 dp 논리 크기가 다르면 정합이 아니다 → dp_gate 참조.
        "resize_ratio": list(resize_ratio),  # 1.0 에서 벗어날수록 패널/프레임 불일치(환경 아티팩트)
        "extent_gate": extent_info,
        "resize_gate": resize_info,
        "rubric": rubric,
    }
    if gate_info:
        metrics["dp_gate"] = gate_info
    else:
        metrics["dp_gate"] = {
            "verdict": "not-checked",
            "note": "--figma-dp/--real-dp 미지정 — dp 불일치를 검사하지 않았다. "
                    "resize_ratio 가 [1.0,1.0] 이어도 dp 가 다를 수 있다(픽셀로는 density 가 상쇄).",
        }

    # rubric 1: blend
    blend = Image.blend(fig_r, real, 0.5)
    blend.save(f"{outdir}/blend50.png")

    if rubric >= 2:
        diff = ImageChops.difference(fig_r, real)
        amp = _amplify(diff)
        amp.save(f"{outdir}/diff.png")
        dstat = diff.convert("L")
        if mask_r is not None:
            # 원래 투명했던 픽셀(라운드 코너 등)은 통계에서 뺀다 — 설계 정보가 없고, 안 빼면 max_diff 가
            # 그 픽셀로 채워져 실제 오차를 가린다(실측: 코너 아티팩트 하나로 max_diff 245).
            vals = [v for v, m in zip(dstat.getdata(), mask_r.getdata()) if m]
            metrics["figma_alpha_excluded_px"] = (real.width * real.height) - len(vals)
        else:
            vals = list(dstat.getdata())
        n = max(1, len(vals))
        over = sum(1 for v in vals if v > DIFF_THRESHOLD)
        metrics["mean_diff"] = round(sum(vals) / n, 2)
        metrics["pct_over_32"] = round(100 * over / n, 2)
        metrics["max_diff"] = max(vals) if vals else 0
        # 임계를 값과 함께 기록한다 — 이 지표가 무엇을 못 보는지 사람이 오해하지 않게.
        metrics["pct_over_32_threshold"] = DIFF_THRESHOLD
        metrics["pct_over_32_note"] = (
            f"픽셀 diff > {DIFF_THRESHOLD} 만 센다. 대비가 이보다 작은 오차는 굵기·길이와 무관하게 항상 0.00 이다 "
            "— 옅은색 구분선·보더·비활성색(예: 흰 배경 위 #E5E5E5 = diff 26)은 이 지표에 잡히지 않는다. "
            "그 카테고리는 edge_probe.py(좌표 비교)로 본다.")

    if rubric >= 3:
        gx, gy = grid
        diff_l = ImageChops.difference(fig_r, real).convert("L")
        if mask_r is not None:      # 셀 랭킹도 투명 픽셀에 끌려가지 않게 — 제외 픽셀만 0 으로 덮는다
            diff_l = diff_l.copy()
            diff_l.paste(0, mask=ImageChops.invert(mask_r))
        cw, ch = real.width // gx, real.height // gy
        cells = []
        for j in range(gy):
            for i in range(gx):
                box = (i * cw, j * ch, (i + 1) * cw, (j + 1) * ch)
                region = diff_l.crop(box)
                m = sum(region.getdata()) / max(1, region.width * region.height)
                cells.append((m, box, (i, j)))
        cells.sort(reverse=True)
        regions = []
        for rank, (m, box, ij) in enumerate(cells[:top]):
            # figma|real 나란히 크롭
            side = Image.new("RGB", (cw * 2 + 8, ch), (255, 255, 255))
            side.paste(fig_r.crop(box), (0, 0))
            side.paste(real.crop(box), (cw + 8, 0))
            name = f"cmp_r{rank}_{ij[0]}-{ij[1]}.png"
            side.save(f"{outdir}/{name}")
            regions.append({
                "rank": rank, "cell": list(ij), "box": list(box),
                "mean_diff": round(m, 2),
                "figma_color": _region_color(fig_r, box),
                "real_color": _region_color(real, box),
                "cmp_img": name,
            })
        metrics["suspect_regions"] = regions

    with open(f"{outdir}/metrics.json", "w") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("figma"); ap.add_argument("real"); ap.add_argument("outdir")
    ap.add_argument("--rubric", type=int, default=3, choices=[1, 2, 3])
    ap.add_argument("--grid", default="12,8")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--blend-only", action="store_true",
                    help="blend50.png 한 장만 생성 (figma/real/diff/cmp/metrics 미생성)")
    ap.add_argument("--figma-dp", type=_parse_dp, default=None,
                    help="Figma 프레임 dp 논리 크기 'WxH' (absoluteBoundingBox)")
    ap.add_argument("--real-dp", type=_parse_dp, default=None,
                    help="캡처 대상 dp 논리 크기 'WxH' (Android: viewport.py verify)")
    ap.add_argument("--allow-extent-mismatch", action="store_true",
                    help="extent·비균일 resize 불일치를 경고로 낮춰 강행 "
                         "(오차 순위가 정답과 반대일 수 있음 — 권장하지 않음)")
    ap.add_argument("--allow-dp-mismatch", action="store_true",
                    help="dp 불일치를 경고로 낮춰 강행 (오차 목록이 유령일 수 있음 — 권장하지 않음)")
    a = ap.parse_args()
    grid = tuple(int(v) for v in a.grid.split(","))
    overlay(a.figma, a.real, a.outdir, a.rubric, grid, a.top, a.blend_only,
            a.figma_dp, a.real_dp, a.allow_dp_mismatch, a.allow_extent_mismatch)
