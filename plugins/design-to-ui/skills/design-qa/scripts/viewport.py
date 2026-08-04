#!/usr/bin/env python3
"""design-qa: 뷰포트 dp 정규화 (Android) — 캡처 **전에** 기기의 dp 논리 크기를 Figma 프레임에 맞춘다.

**왜 캡처보다 먼저인가.** Figma 프레임(예 360×780dp)과 기기(예 411×914dp)의 dp 가 다르면 레이아웃이
**다르게 계산**된다 — 411dp 에서는 카드 설명이 1줄로 줄어드는데 Figma 는 2줄이다. 이건 **어떤 배율로도
되돌릴 수 없다**. 그런데 dp 가 14% 큰 것을 density 가 14% 낮은 것이 상쇄해서 **픽셀 공간에서는 거의 겹치고**,
그래서 스킬이 지시하는 검산이 **전부 통과한다**(실측):

  crop.py frame --figma → `정합 게이트 OK (전역 오프셋 ≤3px)`   ← 초록불인데 틀렸다
  overlay.py            → `resize_ratio [1.0, 1.0256]`          ← 2.6%라 stretch 로 안 읽힘
  crop.py auto          → `box=(0,50,1080,2390)`                ← 상단 50px 잘라 억지 정합
  align_probe           → `drift 후보 7개` (dx-8,dy-24 / dy+23 …) ← 전부 유령
  overlay.py mean_diff  → 8.55 (dp 맞추면 1.45 → 5.9배)

정규화 후: `resize_ratio [1.0, 1.0]`, `mean_diff 1.45`, 유령 drift 0개.

**3단 사다리 (결정 순서).**
  ① Figma 프레임 dp 와 같은 논리 크기의 기기/AVD 가 이미 있으면 그것을 쓴다 — 기기 설정을 건드리지 않으므로
     가장 안전하고 원복 실패 리스크가 없다. (`verify` 로 확인만 하면 된다.)
  ② 없으면 `wm size` 와 `wm density` 를 **함께** 설정한다 (`apply`). 둘을 함께 바꾸면 임의의 프레임 dp 를
     정확히 맞출 수 있다:  density = 160×k,  size = (W×k)×(H×k).
     ⚠️ 기기의 원래 해상도(px)를 유지하려 하지 말 것 — 그러면 density 가 정수로 안 떨어진다(375dp → 460.8).
        `wm size` 를 함께 바꾸는 것이 핵심이고, 이 오해가 "맞출 수 없다"는 오판의 지점이다.
     ⚠️ 물리 해상도보다 **큰** `wm size` 도 동작한다(실측: 1125 > 1080 에서 `screencap` 이 오버라이드 크기를
        그대로 반환 — 패널 크기로 잘리거나 리샘플되지 않는다). 저해상도 기기에서도 @3x 로 맞출 수 있다.
  ③ ①·② 모두 불가면(adb 불가, `wm` 오버라이드가 막힌 기기) **중단하고 사용자에게 알린다** — 오버레이 자체가
     성립하지 않는다. 억지로 crop/배율로 흡수하려 하지 말 것.

k=3(density 480) 권장 — Figma export 를 같은 배율(`defaultScale=k`)로 받으면 픽셀 1:1 로 맞는다. 반정수 dp
프레임은 `W×k` 가 정수가 되는 k 를 고른다(375.5dp → k=2).

**끝나고 반드시 `reset`.** 사용자 기기 상태를 남기지 않는다 — `--freeze`/`--theme` 가 덮어쓴 설정의 **직전
값을 저장해 두었다가 `reset` 이 되돌린다**(저장 안 하면 애니메이션 0·라이트 테마가 기기에 그대로 남는다.
실측으로 남는 것을 확인하고 고친 자리다). `verify` 는 `Override` 행 유무로 정규화 여부를 읽으므로 preflight
로도 쓸 수 있다.

usage:
  python3 viewport.py plan   360x780 [--k 3]            # 명령만 계산 (기기 없이 확인)
  python3 viewport.py apply  360x780 [--k 3] [--freeze] [--theme light]
  python3 viewport.py verify [360x780]                  # 현재 dp 읽기 / 기대값과 대조
  python3 viewport.py reset                             # wm size/density + freeze/theme 원복

기기가 여러 대면 `--serial` 을 넘긴다. 위치는 서브커맨드 앞/뒤 둘 다 받는다.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import time

# k 후보 — 앞쪽 우선. density=160×k 가 정수여야 하고, W×k·H×k 도 정수여야 한다.
K_CANDIDATES = (3, 2, 4, 2.5, 1.5, 6, 1)
DP_TOL = 0.02          # dp 역산 허용 오차 (정수 나눗셈 반올림 흡수)
# 프레임버퍼 리사이즈 대기. `wm size` 는 Override 를 **즉시** 보고하지만 실제 화면(screencap)이 그 크기가
# 되기까지 시간이 걸린다 — 실측(에뮬 API 36, arm64): 명령 반환 0.15s vs screencap 반영 ~1.0-1.1s.
# 그 사이에 캡처하면 **이전 크기 이미지**를 받는다(실측: 360dp 로 바꾼 직후 캡처가 1080x2400 = 원래 크기).
# 그래서 `wm size` 출력이 아니라 **실제 캡처 크기**로 확인한다.
SETTLE_TIMEOUT_S = 15.0
SETTLE_POLL_S = 0.3


def adb(args, serial=None, check=True):
    cmd = ["adb"] + (["-s", serial] if serial else []) + args
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"viewport: `{' '.join(cmd)}` 실패 (rc={p.returncode})\n{p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def _cap_args(serial=None):
    """screencap 의 `-d` 인자 — 구현은 capture.py 에 한 벌만 둔다(테스트도 거기서 한다)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from capture import screencap_args
    except ImportError:
        return []
    return screencap_args(serial)


def capture_size(serial=None):
    """실제 화면(screencap PNG)의 픽셀 크기. PNG IHDR 만 읽어 Pillow 의존을 피한다.

    멀티 디스플레이 기기에서는 `-d <id>` 를 붙여야 한다 — 안 붙이면 경고 문구가 stdout 앞에 붙어
    PNG 가 깨지고, 여기가 None 을 돌려 apply 가 "화면이 안 바뀐다"로 오진한다(capture.screencap_args 주석 참조).
    """
    cmd = ["adb"] + (["-s", serial] if serial else []) + ["exec-out", "screencap", "-p"] + _cap_args(serial)
    p = subprocess.run(cmd, capture_output=True)
    blob = p.stdout
    if len(blob) < 24 or blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", blob[16:24])
    return (w, h)


def wait_capture_size(want, serial=None, timeout=SETTLE_TIMEOUT_S):
    """screencap 이 want 크기가 될 때까지 폴링. (성공?, 마지막 관측값, 걸린 초)"""
    t0 = time.time()
    seen = None
    while time.time() - t0 < timeout:
        seen = capture_size(serial)
        if seen == want:
            return True, seen, time.time() - t0
        time.sleep(SETTLE_POLL_S)
    return False, seen, time.time() - t0


def parse_size(text):
    """`wm size` 출력에서 (physical, override). override 가 없으면 None."""
    phys = re.search(r"Physical size:\s*(\d+)x(\d+)", text)
    over = re.search(r"Override size:\s*(\d+)x(\d+)", text)
    return (tuple(int(v) for v in phys.groups()) if phys else None,
            tuple(int(v) for v in over.groups()) if over else None)


def parse_density(text):
    """`wm density` 출력에서 (physical, override)."""
    phys = re.search(r"Physical density:\s*(\d+)", text)
    over = re.search(r"Override density:\s*(\d+)", text)
    return (int(phys.group(1)) if phys else None,
            int(over.group(1)) if over else None)


def effective(text_size, text_density):
    """실효 해상도·density·dp — override 가 있으면 그것이 실효값이다."""
    ps, os_ = parse_size(text_size)
    pd, od = parse_density(text_density)
    size = os_ or ps
    dens = od if od is not None else pd
    if not size or not dens:
        return None
    dp = (size[0] / dens * 160, size[1] / dens * 160)
    return {"size_px": size, "density": dens, "dp": (round(dp[0], 2), round(dp[1], 2)),
            "overridden": bool(os_ or od is not None)}


def parse_dp(s):
    try:
        w, h = s.lower().replace("×", "x").split("x")
        return (float(w), float(h))
    except Exception:
        sys.exit(f"viewport: dp 크기는 'WxH' 형식이어야 함 (받은 값: {s!r})")


def plan(dp, k_pref=None):
    """프레임 dp → (k, density, size_px). 정수로 떨어지는 k 를 고른다."""
    w, h = dp
    cands = ([k_pref] if k_pref else []) + [k for k in K_CANDIDATES if k != k_pref]
    for k in cands:
        dens = 160 * k
        pw, ph = w * k, h * k
        if abs(dens - round(dens)) > 1e-9:
            continue
        if abs(pw - round(pw)) > 1e-9 or abs(ph - round(ph)) > 1e-9:
            continue
        return (k, int(round(dens)), (int(round(pw)), int(round(ph))))
    sys.exit(f"viewport: {w:g}x{h:g}dp 를 정수 px 로 만드는 k 를 찾지 못함 (후보 {K_CANDIDATES}).\n"
             f"  프레임 dp 소수점이 특이한 경우다 — 사다리 ③(중단·사용자 통보)으로 간다.")


def cmd_plan(a):
    k, dens, (pw, ph) = plan(parse_dp(a.dp), a.k)
    print(f"# {a.dp}dp → k={k:g} (density {dens} = 160×{k:g}, size {pw}x{ph}px)")
    print(f"adb shell wm size {pw}x{ph}")
    print(f"adb shell wm density {dens}")
    print(f"# figma export 는 같은 배율로: download_assets(defaultFormat='png', defaultScale={k:g}) → {pw}x{ph}px")
    print("adb shell wm size reset && adb shell wm density reset   # 끝나고 반드시 원복")


def cmd_apply(a):
    dp = parse_dp(a.dp)
    k, dens, (pw, ph) = plan(dp, a.k)
    # ① 사다리 1단 — 이미 맞으면 기기 설정을 건드리지 않는다.
    cur = effective(adb(["shell", "wm", "size"], a.serial), adb(["shell", "wm", "density"], a.serial))
    if cur and abs(cur["dp"][0] - dp[0]) <= DP_TOL and abs(cur["dp"][1] - dp[1]) <= DP_TOL:
        print(f"사다리 ① — 이미 {cur['dp'][0]:g}x{cur['dp'][1]:g}dp 다. 기기 설정을 건드리지 않는다 "
              f"({cur['size_px'][0]}x{cur['size_px'][1]}px @{cur['density']})")
        cap = capture_size(a.serial)
        if cap and cap != tuple(cur["size_px"]):
            sys.exit(f"viewport: wm 은 {cur['size_px']} 인데 실제 캡처는 {cap} 다 — 아직 리사이즈 중이거나 "
                     "다른 디스플레이를 찍고 있다. 캡처하지 말 것.")
        print(f"검증(screencap): {cap[0]}x{cap[1]}px" if cap else "경고: screencap 을 읽지 못했다")
        if a.freeze:
            _freeze(a)
        if a.theme:
            _set_theme(a)
        return
    print(f"사다리 ② — wm size + wm density 를 함께 설정: {pw}x{ph}px @{dens} (k={k:g})")
    adb(["shell", "wm", "size", f"{pw}x{ph}"], a.serial)
    adb(["shell", "wm", "density", str(dens)], a.serial)
    if a.freeze:
        _freeze(a)
    if a.theme:
        _set_theme(a)
    got = effective(adb(["shell", "wm", "size"], a.serial), adb(["shell", "wm", "density"], a.serial))
    if not got:
        sys.exit("viewport: 적용 후 wm size/density 를 읽지 못했다 — 사다리 ③(중단)")
    ok = abs(got["dp"][0] - dp[0]) <= DP_TOL and abs(got["dp"][1] - dp[1]) <= DP_TOL
    print(f"검증(wm): {got['size_px'][0]}x{got['size_px'][1]}px @{got['density']} "
          f"= {got['dp'][0]:g}x{got['dp'][1]:g}dp  → {'OK' if ok else 'MISMATCH'}")
    if not ok:
        sys.exit(f"viewport: 오버라이드가 먹지 않았다(기대 {dp[0]:g}x{dp[1]:g}dp). "
                 "OEM 펌웨어가 wm 오버라이드를 막는 기기일 수 있다 — 사다리 ③(중단·사용자 통보).")
    # ⚠️ wm 보고만 믿으면 안 된다 — 프레임버퍼 리사이즈는 비동기다(실측 ~1.0s 지연). 여기서 기다리지 않으면
    # 바로 뒤 캡처가 **이전 크기 이미지**로 나오고, 그건 dp 게이트도 통과한다(크기가 예전 값으로 일관되므로).
    settled, seen, took = wait_capture_size((pw, ph), a.serial)
    if not settled:
        sys.exit(f"viewport: {SETTLE_TIMEOUT_S:g}s 안에 실제 화면이 {pw}x{ph}px 가 되지 않았다"
                 f"(마지막 관측 {seen}). 캡처하지 말 것 — 사다리 ③(중단·사용자 통보).")
    print(f"검증(screencap): {seen[0]}x{seen[1]}px — 프레임버퍼 반영 확인 ({took:.1f}s 대기)")
    print(f"figma export 를 {pw}x{ph}px 로 받을 것: download_assets(defaultFormat='png', defaultScale={k:g})")
    print("끝나고 원복: python3 viewport.py reset")


# `--freeze` 가 덮어쓰는 설정. (namespace, key, 값)
# `immersive_mode_confirmations`: 시스템 바를 숨기는 앱은 새 기기에서 "Viewing full screen" 안내
# 다이얼로그가 1회 뜬다. 그게 화면 위쪽을 덮고 나머지를 어둡게 만들어 오버레이를 통째로 망치는데,
# **큰 오차처럼 보이지 도구 실패로는 안 보인다**(실측 mean_diff 5.61 → 90.79, 보정 전후 구별 불가).
# 사람이 기억해서 끄는 대신 여기서 끄고, reset 이 직전값으로 되돌린다.
FROZEN_SETTINGS = (
    ("system", "font_scale", "1.0"),
    ("global", "window_animation_scale", "0"),
    ("global", "transition_animation_scale", "0"),
    ("global", "animator_duration_scale", "0"),
    ("secure", "immersive_mode_confirmations", "confirmed"),
)


def state_path(serial=None):
    """원복용 직전값 저장 위치. 레포·산출물 디렉터리를 더럽히지 않도록 캐시에 둔다."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "design-qa")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"viewport-{serial or 'default'}.json")


def parse_night(text):
    """`cmd uimode night` 출력 → 'yes'|'no'|'auto' (못 읽으면 None).

    출력 형식은 `Night mode: no` 다. 값만 따로 주는 read 명령이 없어서 파싱한다.
    """
    m = re.search(r"Night mode:\s*(\w+)", text or "")
    return m.group(1).lower() if m else None


def _settings_get(ns, key, serial=None):
    """설정 현재값. 미설정이면 adb 가 'null' 을 주는데, 그건 '값 없음'이라 None 으로 돌린다."""
    out = (adb(["shell", "settings", "get", ns, key], serial, check=False) or "").strip()
    return None if out in ("", "null") else out


def _save_state(serial, data):
    with open(state_path(serial), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_state(serial):
    try:
        with open(state_path(serial)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _freeze(a):
    """dp 외 변수 고정 — 접근성 폰트 배율·애니메이션. 줄바꿈/합성 프레임 오판을 막는다.

    ⚠️ 덮어쓰기 **전에 직전값을 저장한다.** 저장하지 않으면 `reset` 이 되돌릴 근거가 없어서 애니메이션 0 이
    사용자 기기에 그대로 남는다 — "기기 상태를 남기지 않는다"는 이 스크립트의 계약을 깨는 자리였다.
    """
    print("dp 외 변수 고정: font_scale=1.0, 애니메이션 0, 전체화면 안내 다이얼로그 off")
    saved = _load_state(a.serial) or {}
    saved.setdefault("settings", {})
    for ns, key, val in FROZEN_SETTINGS:
        # 이미 저장돼 있으면 덮지 않는다 — apply 를 두 번 부르면 '고정된 값'이 직전값으로 박제된다.
        saved["settings"].setdefault(f"{ns}/{key}", _settings_get(ns, key, a.serial))
        adb(["shell", "settings", "put", ns, key, val], a.serial, check=False)
    _save_state(a.serial, saved)


def _set_theme(a):
    """프레임의 다크/라이트에 화면 테마를 맞춘다.

    맞추지 않으면 라이트 프레임을 다크 화면과 대조하게 되고, 그 오버레이는 전면이 오차로 나와 아무것도
    가리키지 못한다(실측: 라이트 프레임 vs 다크 앱에서 캡처 mean 22 vs figma 244).
    """
    want = a.theme
    cur = parse_night(adb(["shell", "cmd", "uimode", "night"], a.serial, check=False))
    saved = _load_state(a.serial) or {}
    saved.setdefault("uimode_night", cur)
    _save_state(a.serial, saved)
    adb(["shell", "cmd", "uimode", "night", "yes" if want == "dark" else "no"], a.serial, check=False)
    print(f"테마 고정: {want} (직전값 {cur or '읽지 못함'})")


def _restore_state(a):
    """`--freeze`/`--theme` 로 바꾼 설정을 직전값으로 되돌린다."""
    saved = _load_state(a.serial)
    if not saved:
        return
    for kk, val in (saved.get("settings") or {}).items():
        ns, key = kk.split("/", 1)
        if val is None:
            adb(["shell", "settings", "delete", ns, key], a.serial, check=False)
        else:
            adb(["shell", "settings", "put", ns, key, val], a.serial, check=False)
    night = saved.get("uimode_night")
    if night:
        adb(["shell", "cmd", "uimode", "night", night], a.serial, check=False)
    try:
        os.unlink(state_path(a.serial))
    except OSError:
        pass
    bits = []
    if saved.get("settings"):
        bits.append("font_scale·애니메이션")
    if night:
        bits.append(f"테마({night})")
    if bits:
        print("설정 원복: " + " / ".join(bits))


def cmd_verify(a):
    got = effective(adb(["shell", "wm", "size"], a.serial), adb(["shell", "wm", "density"], a.serial))
    if not got:
        sys.exit("viewport: wm size/density 를 읽지 못했다 (adb 연결 확인)")
    state = "정규화됨(Override 있음)" if got["overridden"] else "기본값(Override 없음)"
    print(f"현재: {got['size_px'][0]}x{got['size_px'][1]}px @{got['density']} "
          f"= {got['dp'][0]:g}x{got['dp'][1]:g}dp — {state}")
    # 실제 화면이 wm 보고와 같은지 본다 — 다르면 리사이즈가 아직 안 끝난 것이고, 그 상태의 캡처는 무효다.
    cap = capture_size(a.serial)
    if cap is None:
        print("경고: screencap 을 읽지 못했다 — wm 보고만으로 판단 중")
    elif cap != tuple(got["size_px"]):
        cap_dp = (round(cap[0] / got["density"] * 160, 2), round(cap[1] / got["density"] * 160, 2))
        sys.exit(f"viewport: wm 은 {got['size_px'][0]}x{got['size_px'][1]}px 인데 실제 캡처는 "
                 f"{cap[0]}x{cap[1]}px (= {cap_dp[0]:g}x{cap_dp[1]:g}dp) 다.\n"
                 "  프레임버퍼 리사이즈가 아직 안 끝났다(실측 ~1.0s 지연) — 캡처하지 말 것. "
                 "`viewport.py apply` 는 이 대기를 자동으로 한다.")
    else:
        print(f"검증(screencap): {cap[0]}x{cap[1]}px — wm 보고와 일치")
    if not a.dp:
        print(f"# overlay.py 에 넘길 값: --real-dp {got['dp'][0]:g}x{got['dp'][1]:g}")
        return
    want = parse_dp(a.dp)
    ok = abs(got["dp"][0] - want[0]) <= DP_TOL and abs(got["dp"][1] - want[1]) <= DP_TOL
    print(f"기대 {want[0]:g}x{want[1]:g}dp → {'OK' if ok else 'MISMATCH'}")
    if not ok:
        sys.exit("viewport: dp 불일치 — 캡처하지 말 것. `viewport.py apply` 로 맞추거나 사다리 ③(중단).")


def cmd_reset(a):
    adb(["shell", "wm", "size", "reset"], a.serial, check=False)
    adb(["shell", "wm", "density", "reset"], a.serial, check=False)
    _restore_state(a)
    got = effective(adb(["shell", "wm", "size"], a.serial), adb(["shell", "wm", "density"], a.serial))
    if not got:
        print("원복 명령 실행 (상태 확인 불가 — adb 연결 확인)")
        return
    print(f"원복: {got['size_px'][0]}x{got['size_px'][1]}px @{got['density']} "
          f"= {got['dp'][0]:g}x{got['dp'][1]:g}dp"
          + ("  ⚠️ Override 가 아직 남아 있다" if got["overridden"] else "  (Override 없음)"))
    # 리사이즈가 끝나기 전에 다음 작업이 캡처하면 여전히 정규화된 크기를 받는다 — 여기서 흡수한다.
    settled, seen, took = wait_capture_size(tuple(got["size_px"]), a.serial)
    if settled:
        print(f"검증(screencap): {seen[0]}x{seen[1]}px — 프레임버퍼 원복 확인 ({took:.1f}s 대기)")
    else:
        print(f"⚠️ 실제 화면이 {got['size_px'][0]}x{got['size_px'][1]}px 로 돌아오지 않았다 (마지막 {seen}) "
              "— 기기 상태를 직접 확인할 것")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=None, help="adb -s 대상 (기기 여러 대)")
    sub = ap.add_subparsers(dest="mode", required=True)

    def add_serial(p):
        """서브커맨드 뒤의 `--serial` 도 받는다 (전역 인자만 두면 여기서 죽는다).

        SUPPRESS 라서 서브커맨드에서 안 주면 전역값을 덮지 않는다.
        """
        p.add_argument("--serial", default=argparse.SUPPRESS, help="adb -s 대상 (전역과 같은 인자)")

    p = sub.add_parser("plan", help="명령만 계산 (기기 없이)")
    p.add_argument("dp", help="Figma 프레임 dp 'WxH' (예 360x780)")
    p.add_argument("--k", type=float, default=None, help="배율 k (기본: 3 우선 자동)")
    add_serial(p)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("apply", help="wm size+density 설정 후 검증")
    p.add_argument("dp", help="Figma 프레임 dp 'WxH'")
    p.add_argument("--k", type=float, default=None)
    p.add_argument("--freeze", action="store_true", help="font_scale·애니메이션도 고정 (reset 이 원복)")
    p.add_argument("--theme", choices=("dark", "light"), default=None,
                   help="Figma 프레임의 다크/라이트에 화면 테마를 맞춘다 (reset 이 원복)")
    add_serial(p)
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("verify", help="현재 dp 읽기 / 기대값 대조")
    p.add_argument("dp", nargs="?", default=None, help="기대 dp 'WxH' (없으면 현재값만 출력)")
    add_serial(p)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("reset", help="wm size/density reset (원복)")
    add_serial(p)
    p.set_defaults(fn=cmd_reset)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
