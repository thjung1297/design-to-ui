#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 실기기/에뮬레이터 풀스크린 캡처.

adb exec-out screencap 으로 PNG 를 받아 저장한다. 인프라 0 — 빌드된 앱 + adb 만 필요.

⚠️ **잠든 기기는 전부 검정으로 캡처된다.** `screencap` 은 화면이 꺼져 있어도 **성공을 반환하고** 올바른 크기의
PNG 를 준다 — 내용만 단색 검정이다(실측: `mWakefulness=Asleep` 에서 mean 0.00 / 고유색 1개). 크기가 맞으니
viewport 의 dp 게이트도, PNG 시그니처 검사도 전부 통과하고, 오버레이만 "전면이 오차"로 나온다. 그래서 캡처
전에 깨우고, 캡처 후 단색이면 여기서 멈춘다.

단색 검사는 "다른 화면"을 못 잡는다 — 런처 홈이 찍혀도 전 게이트가 통과한다(실측 mean_diff 57.21).
`--expect-package <pkg>` 로 포그라운드를 검증한다 (불일치면 멈춘다).

usage:
    python3 capture.py <out.png> [--serial <adb-serial>] [--no-wake] [--expect-package <pkg>]
"""
# PEP 604 애노테이션(`str | None`)이 3.9 에서 def 시점에 평가돼 죽는 것을 막는다 (macOS 시스템 python3).
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time

# 깨운 뒤 화면이 실제로 그려질 때까지의 대기 (viewport 의 프레임버퍼 대기와 같은 성격).
SETTLE_TIMEOUT_S = 8.0
SETTLE_POLL_S = 0.4


def _adb(args, serial: str | None = None) -> str:
    cmd = ["adb"] + (["-s", serial] if serial else []) + args
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def wakefulness(serial: str | None = None) -> str | None:
    """`dumpsys power` 의 mWakefulness — 'Awake'|'Asleep'|'Dozing'|'Dreaming' (못 읽으면 None)."""
    m = re.search(r"mWakefulness=(\w+)", _adb(["shell", "dumpsys", "power"], serial))
    return m.group(1) if m else None


def ensure_awake(serial: str | None = None) -> None:
    """잠들어 있으면 깨우고 키가드를 내린다. 깨우지 못하면 캡처하지 않고 멈춘다."""
    state = wakefulness(serial)
    if state is None or state == "Awake":
        return
    print(f"기기가 {state} 상태 — 깨운다 (KEYCODE_WAKEUP + dismiss-keyguard)")
    _adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serial)
    _adb(["shell", "wm", "dismiss-keyguard"], serial)
    state = wakefulness(serial)
    if state != "Awake":
        sys.exit(f"capture: 기기를 깨우지 못했다 (mWakefulness={state}). 잠든 화면은 전부 검정으로 캡처되고 "
                 "그 이미지는 크기 검사·dp 게이트를 전부 통과한다 — 캡처하지 말 것.")


def current_focus(serial: str | None = None):
    """`dumpsys window` 의 mCurrentFocus 목록 — 멀티 디스플레이면 화면당 하나씩 나온다."""
    out = _adb(["shell", "dumpsys", "window"], serial)
    return [m for m in re.findall(r"mCurrentFocus=(?:Window\{[^}]*?\s(\S+)\}|null)", out)]


def ensure_focus(expect_package: str, serial: str | None = None) -> None:
    """대상 앱이 포그라운드인지 확인한다. 아니면 캡처하지 않고 멈춘다.

    단색 검사는 검정 화면만 잡고 "그럴듯한 다른 화면"은 통과시킨다 — 실측: monkey 런치가 조용히 실패해
    런처 홈이 찍혔는데 dp·extent·resize 게이트가 전부 ok 인 채 mean_diff 57.21 만 남았다.
    """
    focus = current_focus(serial)
    if not focus:
        sys.exit(f"capture: mCurrentFocus 를 읽지 못했다 — {expect_package} 가 포그라운드인지 확인할 수 없다.")
    if not any(expect_package in f for f in focus):
        sys.exit(f"capture: 포그라운드가 {expect_package} 가 아니다 (mCurrentFocus={focus}). "
                 f"`adb shell am start -W -n {expect_package}/.MainActivity` 로 먼저 진입할 것.")


def uniform_color(png_path: str):
    """단색 이미지면 그 색을 돌려준다 (아니면 None). Pillow 가 없으면 검사를 건너뛴다."""
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(png_path) as im:
        colors = im.convert("RGB").getcolors(maxcolors=2)
    # getcolors 는 색 종류가 maxcolors 를 넘으면 None — 즉 None 이면 '단색 아님'이다.
    return colors[0][1] if colors and len(colors) == 1 else None


def display_ids(serial: str | None = None):
    """`dumpsys SurfaceFlinger --display-id` 의 디스플레이 id 목록 (없으면 빈 리스트)."""
    out = _adb(["shell", "dumpsys", "SurfaceFlinger", "--display-id"], serial)
    return re.findall(r"^Display (\d+)", out, re.M)


def wm_size(serial: str | None = None):
    """`wm size` 의 실효 크기 — Override 가 있으면 그것 (없으면 Physical)."""
    out = _adb(["shell", "wm", "size"], serial)
    m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _cap_size(serial: str | None, display: str):
    """해당 디스플레이를 찍어 PNG 크기만 읽는다 (IHDR — Pillow 불요)."""
    import struct
    cmd = ["adb"] + (["-s", serial] if serial else []) + ["exec-out", "screencap", "-p", "-d", display]
    blob = subprocess.run(cmd, capture_output=True).stdout
    if len(blob) < 24 or blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", blob[16:24])


_DISPLAY_CACHE = {}


def screencap_args(serial: str | None = None, display: str | None = None):
    """`screencap` 에 붙일 `-d` 인자.

    ⚠️ **멀티 디스플레이 기기(resizable·foldable AVD)에서 `-d` 없이 부르면 PNG 가 깨진다.** screencap 이
    `[Warning] Multiple displays were found, but no display id was specified!` 를 **stdout 앞에 붙여** 보내서
    바이너리가 오염된다(실측: 앞 120바이트가 경고 문구, PNG 시그니처 없음).

    ⚠️ **"첫 번째 디스플레이"는 답이 아니다.** `wm` 오버라이드가 어느 디스플레이에 걸리는지는 구성에 따라
    다르다 — 실측(REAR_DISPLAY_MODE): `EMU_display_0` 은 1080x2400 그대로인데 정규화한 1080x2340 은
    `EMU_display_1` 에 걸렸다. 첫 id 를 찍으면 **정규화하지 않은 화면**을 대조하게 된다. 그래서 `wm` 이
    보고하는 크기와 **실제로 일치하는** 디스플레이를 고른다(리사이즈 대기 중엔 아직 아무것도 일치하지
    않는데, 그때는 첫 id 로 두어 호출자의 프레임버퍼 대기가 그대로 동작하게 한다).
    """
    if display:
        return ["-d", display]
    ids = display_ids(serial)
    if len(ids) < 2:
        return []
    want = wm_size(serial)
    cached = _DISPLAY_CACHE.get(serial)
    if cached and want and _cap_size(serial, cached) == want:
        return ["-d", cached]
    for d in ids:
        if want and _cap_size(serial, d) == want:
            _DISPLAY_CACHE[serial] = d
            return ["-d", d]
    return ["-d", ids[0]]


def _screencap(out_path: str, serial: str | None = None, display: str | None = None) -> int:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["exec-out", "screencap", "-p"] + screencap_args(serial, display)
    png = subprocess.run(cmd, capture_output=True).stdout
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
        head = png[:80].decode("utf-8", "replace") if png else ""
        hint = f"\n  받은 앞부분: {head!r}" if head else ""
        sys.exit("capture failed — adb 연결/기기 상태 확인 (PNG 시그니처 없음)." + hint +
                 "\n  멀티 디스플레이 기기면 `--display <id>` 로 지정한다 "
                 "(`adb shell dumpsys SurfaceFlinger --display-id`).")
    with open(out_path, "wb") as f:
        f.write(png)
    return len(png)


def capture(out_path: str, serial: str | None = None, wake: bool = True,
            settle_timeout: float = SETTLE_TIMEOUT_S, display: str | None = None,
            expect_package: str | None = None) -> None:
    if wake:
        ensure_awake(serial)
    if expect_package:
        ensure_focus(expect_package, serial)
    size = _screencap(out_path, serial, display)
    solid = uniform_color(out_path)
    # ⚠️ `mWakefulness=Awake` 가 되어도 **프레임버퍼는 아직 검정이다** — wm 리사이즈와 같은 종류의 지연이라
    # 깨운 직후 캡처는 단색으로 나온다(실측). 그래서 상태값이 아니라 **실제 픽셀**이 그려질 때까지 기다린다.
    if solid is not None and wake:
        t0 = time.time()
        while solid is not None and time.time() - t0 < settle_timeout:
            time.sleep(SETTLE_POLL_S)
            size = _screencap(out_path, serial, display)
            solid = uniform_color(out_path)
        if solid is None:
            print(f"화면이 그려질 때까지 {time.time() - t0:.1f}s 대기함")
    if solid is not None:
        sys.exit(f"capture: 캡처가 단색 {solid} 이다 — 화면이 꺼졌거나 보안 화면(FLAG_SECURE)이라 내용이 안 잡힌 것. "
                 "이 이미지로 오버레이를 돌리면 전면이 오차로 나온다.")
    print(f"captured {size} bytes -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--no-wake", dest="wake", action="store_false",
                    help="깨우기 생략 (꺼진 화면을 의도적으로 찍을 때만)")
    ap.add_argument("--display", default=None,
                    help="멀티 디스플레이 기기의 대상 display id (기본: 첫 번째를 명시 지정)")
    ap.add_argument("--expect-package", default=None,
                    help="이 패키지가 포그라운드가 아니면 캡처하지 않고 멈춘다 (엉뚱한 화면은 전 게이트를 통과한다)")
    a = ap.parse_args()
    capture(a.out, a.serial, a.wake, display=a.display, expect_package=a.expect_package)
