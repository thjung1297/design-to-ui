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

usage:
    python3 overlay.py <figma.png> <real.png> <outdir> --rubric 3 [--grid 12,8] [--top 5]
    python3 overlay.py <figma.png> <real.png> <outdir> --blend-only
"""
import argparse
import json
import os

from PIL import Image, ImageChops, ImageOps


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


def overlay(figma_path, real_path, outdir, rubric, grid, top, blend_only=False):
    os.makedirs(outdir, exist_ok=True)
    real = Image.open(real_path).convert("RGB")
    fig = Image.open(figma_path).convert("RGB")
    resize_ratio = (round(real.width / fig.width, 4), round(real.height / fig.height, 4))
    fig_r = fig.resize(real.size)

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
        "resize_ratio": list(resize_ratio),  # 1.0 에서 벗어날수록 패널/프레임 불일치(환경 아티팩트)
        "rubric": rubric,
    }

    # rubric 1: blend
    blend = Image.blend(fig_r, real, 0.5)
    blend.save(f"{outdir}/blend50.png")

    if rubric >= 2:
        diff = ImageChops.difference(fig_r, real)
        amp = _amplify(diff)
        amp.save(f"{outdir}/diff.png")
        dstat = diff.convert("L")
        vals = list(dstat.getdata())
        n = len(vals)
        over = sum(1 for v in vals if v > 32)
        metrics["mean_diff"] = round(sum(vals) / n, 2)
        metrics["pct_over_32"] = round(100 * over / n, 2)
        metrics["max_diff"] = max(vals)

    if rubric >= 3:
        gx, gy = grid
        diff_l = ImageChops.difference(fig_r, real).convert("L")
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
    a = ap.parse_args()
    grid = tuple(int(v) for v in a.grid.split(","))
    overlay(a.figma, a.real, a.outdir, a.rubric, grid, a.top, a.blend_only)
