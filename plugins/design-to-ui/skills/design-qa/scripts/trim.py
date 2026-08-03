#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa web: 흰 여백 트림 — 웹 캡처↔Figma export 의 프레이밍(주변 padding) 차이를 제거한다.

design-qa 의 crop.py `auto`(content 매칭)의 웹 경량판. 웹은 배경이 대부분 단색(흰/토큰배경)이라
"콘텐츠 bbox"로 잘라 두 이미지의 프레이밍을 맞추면 오버레이 오프셋 오판이 사라진다.
near-white(임계 이내) 테두리를 잘라 콘텐츠 경계로 정규화한다.

usage: python3 trim.py <in.png> <out.png> [--thr 12]
"""
import argparse
from PIL import Image, ImageChops


def trim(in_path, out_path, thr):
    im = Image.open(in_path).convert("RGB")
    # 좌상단 픽셀을 배경색으로 가정하고 그와의 차이가 thr 이하인 테두리를 제거
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg).convert("L")
    mask = diff.point(lambda v: 255 if v > thr else 0)
    box = mask.getbbox()
    if box:
        im = im.crop(box)
    im.save(out_path)
    print(f"{in_path} -> {out_path}  bbox={box} size={im.size}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--thr", type=int, default=12)
    a = ap.parse_args()
    trim(a.inp, a.out, a.thr)
