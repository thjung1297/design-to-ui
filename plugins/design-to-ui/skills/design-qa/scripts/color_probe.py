#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: per-text 의미색 프로브 — "색=의미" 텍스트 fill을 figma 토큰값과 수치 대조.

overlay 평균·눈대중이 놓치는 작은 의미색(게이지 등급, min/max 온도, 경보 등)을 기계적으로 잡는다.
각 영역의 대표색(가장 진한 픽셀 = 텍스트 획)을 real에서 떠 기대 hex(figma 토큰)와 유클리드 거리로 비교.

웹 이식: `--mode` 로 대표색 선정 방향을 고른다. 어두운글자/밝은배경(기본 dark=darkest)은 원본 그대로,
흰글자/컬러배경(활성탭·CTA·뱃지 등 반전 컨텍스트)은 `light`(brightest)로 텍스트 획을 잡는다.

usage:
  python3 color_probe.py <real.png> --regions "good:L,T,R,B=#2B6FD7; normal:L,T,R,B=#00893D" [--thr 24] [--mode dark|light]
"""
import argparse
from PIL import Image


def rep_color(img, box, mode="dark"):
    px = list(img.crop(box).convert("RGB").getdata())
    # dark: 가장 진한 픽셀 = 밝은 배경 위 텍스트 획. light: 가장 밝은 픽셀 = 컬러 배경 위 흰 텍스트 획.
    key = (lambda p: p[0] + p[1] + p[2])
    return (min if mode == "dark" else max)(px, key=key)


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("real")
    ap.add_argument("--regions", required=True, help="'name:L,T,R,B=#RRGGBB; ...'")
    ap.add_argument("--thr", type=int, default=24, help="색 거리 임계 (기본 24)")
    ap.add_argument("--mode", choices=["dark", "light"], default="dark",
                    help="대표색 방향: dark=darkest(밝은배경 위 어두운글자), light=brightest(컬러배경 위 흰글자)")
    a = ap.parse_args()

    img = Image.open(a.real).convert("RGB")
    print(f"# color_probe thr={a.thr} mode={a.mode}")
    flagged = []
    for part in a.regions.split(";"):
        part = part.strip()
        if not part:
            continue
        name, rest = part.split(":")
        coords, hexv = rest.split("=")
        box = tuple(int(v) for v in coords.split(","))
        rc = rep_color(img, box, a.mode)
        exp = hex2rgb(hexv)
        d = sum((rc[i] - exp[i]) ** 2 for i in range(3)) ** 0.5
        tag = "" if d <= a.thr else "  <-- COLOR MISMATCH (figma 토큰과 다름)"
        if d > a.thr:
            flagged.append(name.strip())
        print(f"{name.strip():>10} real={rc} expect={exp} dist={d:.1f}{tag}")
    print(f"\n# 색 불일치 {len(flagged)}개" + ("" if flagged else " — 의미색 정합 OK"))


if __name__ == "__main__":
    main()
