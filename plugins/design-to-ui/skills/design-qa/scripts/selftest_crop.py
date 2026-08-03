#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""crop.py 셀프테스트 — 합성 캡처로 auto/gate/anchor/frame 를 의존성·기기 없이 검증한다.

실행: python3 selftest_crop.py   (PIL 만 필요, 종료코드 0=전부 PASS)

커버:
  A) auto 위치 복원 (scale 1)         — 알려진 오프셋 ±2px 복원
  B) auto 스케일 복원 (2x, density)    — 스케일·오프셋 복원 (mdpi 아닌 기기 대응)
  C) auto 디코이 오검출 방지           — 유사 구조 방해물이 있어도 진짜 위치 락
  D) 정합 게이트                       — 정렬시 무경고 / 오프셋시 경고
  E) anchor CLI 회귀                   — 임베드 앵커 박스 산출
  F) frame 정규식 회귀                 — dumpsys frame 파싱
"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crop", os.path.join(HERE, "crop.py"))
crop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crop)

CAND = (1, 2, 3, 1.5, 0.5, 0.75)
DS = (8, 2)
_results = []


def check(name, cond, detail=""):
    _results.append(cond)
    print(("  PASS" if cond else "  FAIL") + f"  {name}  {detail}")


def make_template(w=300, h=200):
    """엣지가 뚜렷한 구별력 있는 템플릿 (카드/해/막대/게이지 바)."""
    im = Image.new("RGB", (w, h), (237, 240, 244))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([10, 10, w - 10, h - 10], 20, fill=(255, 255, 255))
    d.ellipse([30, 40, 110, 120], fill=(255, 200, 0))
    d.rectangle([140, 40, 150, 120], fill=(20, 20, 20))
    d.rounded_rectangle([160, 50, 280, 70], 8, fill=(43, 111, 215))
    d.rounded_rectangle([160, 90, 260, 110], 8, fill=(0, 137, 61))
    for i in range(5):
        d.line([30 + i * 20, 150, 30 + i * 20, 180], fill=(0, 0, 0), width=3)
    return im


def canvas(w, h, bg=(180, 182, 186)):
    return Image.new("RGB", (w, h), bg)


def run():
    tmpl = make_template()

    # A) 위치 복원 (scale 1)
    cap = canvas(900, 600)
    cap.paste(tmpl, (150, 90))
    L, T, R, B, s, _ = crop.auto_box(cap, tmpl, DS, None, CAND)
    check("A auto 위치 복원", abs(L - 150) <= 2 and abs(T - 90) <= 2 and abs(s - 1.0) < 1e-6,
          f"box=({L},{T}) s={s:g} (기대 150,90 s1)")

    # B) 스케일 복원 (2x)
    cap = canvas(1200, 900)
    cap.paste(tmpl.resize((tmpl.width * 2, tmpl.height * 2)), (200, 150))
    L, T, R, B, s, _ = crop.auto_box(cap, tmpl, DS, None, CAND)
    check("B auto 스케일 복원(2x)",
          abs(L - 200) <= 4 and abs(T - 150) <= 4 and abs(s - 2.0) < 1e-6 and abs((R - L) - tmpl.width * 2) <= 2,
          f"box=({L},{T},{R},{B}) s={s:g} (기대 200,150 s2)")

    # C) 디코이 오검출 방지
    cap = canvas(1000, 700)
    decoy = tmpl.convert("L").convert("RGB").filter(ImageFilter.GaussianBlur(4))
    cap.paste(decoy, (40, 40))
    cap.paste(tmpl, (400, 250))
    L, T, R, B, s, _ = crop.auto_box(cap, tmpl, DS, None, CAND)
    check("C auto 디코이 오검출 방지", abs(L - 400) <= 3 and abs(T - 250) <= 3,
          f"box=({L},{T}) (진짜 400,250 / 디코이 40,40)")

    # D) 정합 게이트
    cap = canvas(900, 600)
    cap.paste(tmpl, (150, 90))
    ok = cap.crop((150, 90, 150 + tmpl.width, 90 + tmpl.height))
    dx, dy, base, score = crop.global_offset(ok, tmpl)
    check("D 게이트 정렬시 무경고", max(abs(dx), abs(dy)) <= crop.GATE_THR_PX, f"dx{dx:+d},dy{dy:+d}")
    off = cap.crop((135, 90, 135 + tmpl.width, 90 + tmpl.height))  # 15px 오프셋
    dx, dy, base, score = crop.global_offset(off, tmpl)
    warn = max(abs(dx), abs(dy)) > crop.GATE_THR_PX and (base - score) > 0.5
    check("D 게이트 오프셋(15px) 경고", warn, f"dx{dx:+d},dy{dy:+d}")

    # E) anchor CLI 회귀
    cp = os.path.join(tempfile.gettempdir(), "st_cap.png")
    op = os.path.join(tempfile.gettempdir(), "st_anchor.png")
    canvas(3000, 1500).save(cp)
    subprocess.run([sys.executable, os.path.join(HERE, "crop.py"), "anchor", cp, op,
                    "--cap-anchor", "2470,150", "--fig-anchor", "1620,60", "--panel-size", "1700,1184"],
                   check=True, capture_output=True)
    check("E anchor CLI 회귀", Image.open(op).size == (1700, 1184), f"size={Image.open(op).size}")

    # F) frame_box — 구/현행 dumpsys 포맷 + 임베디드 (0,0) 가드
    def frame_of(dump):
        crop._dumpsys_windows = lambda serial: dump
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            box = crop.frame_box("com.nhn.android.search", "MainActivity", None)
        return box, ("⚠️" in err.getvalue())

    # F1 구 포맷 (한 줄, 콤마 4개)
    b, c = frame_of("x com.nhn.android.search/com.nhn.android.search.MainActivity, frame=[840,96,2540,1280] y")
    check("F1 frame 구포맷(comma)", b == (840, 96, 2540, 1280) and not c, f"{b} caution={c}")
    # F2 현행 포맷 (멀티라인, 대괄호 쌍)
    b, c = frame_of("Window{a u10 com.nhn.android.search/com.nhn.android.search.MainActivity}:\n"
                    "  Frames: parent=[0,0][2560,1440] display=[0,0][2560,1440] frame=[840,96][2540,1280] last=[..]\n")
    check("F2 frame 현행포맷(bracket-pair)", b == (840, 96, 2540, 1280) and not c, f"{b} caution={c}")
    # F3 임베디드 로컬좌표 (원점 0,0) → 매칭하되 caution
    b, c = frame_of("Window{a u10 com.nhn.android.search/com.nhn.android.search.MainActivity}:\n"
                    "  Frames: display=[0,0][1700,1184] frame=[0,0][1700,1184]\n")
    check("F3 임베디드(0,0) 가드 경고", b == (0, 0, 1700, 1184) and c, f"{b} caution={c}")

    n = sum(_results)
    print(f"\n== {n}/{len(_results)} PASS ==")
    return 0 if n == len(_results) else 1


if __name__ == "__main__":
    sys.exit(run())
