#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""viewport.py 오프라인 검증 — adb 를 가짜로 갈아끼워 사다리 분기·원복·오버라이드 실패를 검사한다.

기기 없이 검증 가능한 항목: #181 검증법 4번(정규화된 환경에서 불필요한 조작 안 함) / 5번(원복 실행).

가짜 기기는 **프레임버퍼 지연까지 흉내낸다.** 실기 실측(에뮬 API 36 arm64): `wm size` 는 Override 를
0.15s 에 보고하는데 `screencap` 이 실제로 그 크기가 되는 건 ~1.0-1.1s 뒤다. 그 사이에 캡처하면 이전 크기
이미지를 받으므로, viewport 가 wm 보고만 믿고 OK 를 주면 안 된다 — 그 회귀를 여기서 막는다.
"""
import os
import sys
import types

# SKD(design-qa 경로)가 오면 그것을, 없으면 이 파일 위치(scripts/selftest)의 상위 scripts/ 를 쓴다.
_SKD = os.environ.get("SKD") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_SKD, "scripts"))
import viewport

CALLS = []


class FakeDevice:
    """wm size / wm density + 지연되는 프레임버퍼를 흉내내는 가짜 기기.

    fb_lag_polls: screencap 이 새 크기를 돌려주기까지 필요한 폴링 횟수(실기의 ~1s 지연 대응).
                  None 이면 영원히 반영되지 않는다(리사이즈가 먹지 않는 기기).
    """

    def __init__(self, phys_size=(1080, 2400), phys_den=420, ov_size=None, ov_den=None,
                 accept_override=True, fb_lag_polls=3):
        self.phys_size, self.phys_den = phys_size, phys_den
        self.ov_size, self.ov_den = ov_size, ov_den
        self.accept_override = accept_override
        self.fb_lag_polls = fb_lag_polls
        self.fb = ov_size or phys_size      # 실제 프레임버퍼 크기 (screencap 이 보는 것)
        self.pending = None                 # 목표 크기
        self.polls = 0
        # `--freeze`/`--theme` 가 건드리는 기기 상태. 원복이 **직전값으로** 돌아오는지 보려면
        # 기본값이 아닌 값에서 출발해야 한다(애니메이션 1.0, 다크).
        self.settings = {"system/font_scale": "1.15", "global/window_animation_scale": "1.0",
                         "global/transition_animation_scale": "1.0",
                         "global/animator_duration_scale": "1.0"}
        # immersive_mode_confirmations 는 **미설정**에서 출발한다 — freeze 가 켠 뒤 reset 이
        # `settings delete` 로 되돌려야 한다(직전값 None 을 그대로 보존하는지 검사).
        self.night = "yes"

    def _target(self):
        return self.ov_size or self.phys_size

    def capture_size(self, serial=None):
        """screencap 대역 — 목표와 다르면 lag 만큼 이전 크기를 계속 돌려준다."""
        want = self._target()
        if self.fb == want:
            return self.fb
        if self.fb_lag_polls is None:       # 절대 반영되지 않음
            return self.fb
        self.polls += 1
        if self.polls >= self.fb_lag_polls:
            self.fb = want
            self.polls = 0
        return self.fb

    def run(self, args, serial=None, check=True):
        CALLS.append(" ".join(args))
        if args[:3] == ["shell", "wm", "size"]:
            if len(args) == 4 and args[3] == "reset":
                self.ov_size = None; return ""
            if len(args) == 4:
                if self.accept_override:
                    self.ov_size = tuple(int(v) for v in args[3].split("x"))
                return ""
            out = f"Physical size: {self.phys_size[0]}x{self.phys_size[1]}\n"
            if self.ov_size:
                out += f"Override size: {self.ov_size[0]}x{self.ov_size[1]}\n"
            return out
        if args[:3] == ["shell", "wm", "density"]:
            if len(args) == 4 and args[3] == "reset":
                self.ov_den = None; return ""
            if len(args) == 4:
                if self.accept_override:
                    self.ov_den = int(args[3])
                return ""
            out = f"Physical density: {self.phys_den}\n"
            if self.ov_den is not None:
                out += f"Override density: {self.ov_den}\n"
            return out
        if args[:2] == ["shell", "settings"]:
            op, ns, key = args[2], args[3], args[4]
            kk = f"{ns}/{key}"
            if op == "get":
                return self.settings.get(kk, "null") + "\n"
            if op == "put":
                self.settings[kk] = args[5]
            elif op == "delete":
                self.settings.pop(kk, None)
            return ""
        if args[:4] == ["shell", "cmd", "uimode", "night"]:
            if len(args) == 5:
                self.night = args[4]
                return ""
            return f"Night mode: {self.night}\n"
        return ""


def scenario(title, dev, fn, expect_exit=None):
    global CALLS
    CALLS = []
    viewport.adb = dev.run
    viewport.capture_size = dev.capture_size      # screencap 대역 (프레임버퍼 지연 포함)
    viewport.SETTLE_POLL_S = 0                    # 테스트는 실시간 대기 없이 폴링만
    print(f"\n### {title}")
    code = None
    try:
        fn()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        print(f"   [exit {code}] {e}" if not isinstance(e.code, int) else f"   [exit {code}]")
    mutating = [c for c in CALLS if len(c.split()) == 4 and "reset" not in c]
    print(f"   변경 명령: {mutating or '없음'}")
    ok = (code is None) if expect_exit is None else (code == expect_exit)
    print(f"   → {'PASS' if ok else 'FAIL (기대 exit=%s, 실제 %s)' % (expect_exit, code)}")
    return ok


A = types.SimpleNamespace
results = []

# ① 이미 dp 가 맞는 기기 — 설정을 건드리면 안 된다 (#181 검증법 4: 불필요한 조작 없음)
dev = FakeDevice(phys_size=(1080, 2340), phys_den=480)          # = 360x780dp
results.append(scenario("사다리 ① 이미 360x780dp — 조작 없어야", dev,
                        lambda: viewport.cmd_apply(A(dp="360x780", k=None, freeze=False, theme=None, serial=None))))
assert not [c for c in CALLS if len(c.split()) == 4 and "reset" not in c], "사다리 ①에서 기기를 건드렸다"

# ② 기본값 411dp 기기 — wm size + density 를 함께 설정해야
dev = FakeDevice()
results.append(scenario("사다리 ② 411dp → 360x780dp 정규화", dev,
                        lambda: viewport.cmd_apply(A(dp="360x780", k=None, freeze=False, theme=None, serial=None))))
assert "shell wm size 1080x2340" in CALLS and "shell wm density 480" in CALLS, "size/density 를 함께 안 바꿨다"

# ③ 오버라이드가 막힌 기기 — 검증 실패로 중단해야 (조용히 진행 금지)
dev = FakeDevice(accept_override=False)
results.append(scenario("사다리 ③ wm 오버라이드 거부 기기 — 중단해야", dev,
                        lambda: viewport.cmd_apply(A(dp="360x780", k=None, freeze=False, theme=None, serial=None)),
                        expect_exit=1))

# verify — 기대 dp 와 다르면 중단
dev = FakeDevice()
results.append(scenario("verify 411dp vs 기대 360x780dp — 중단해야", dev,
                        lambda: viewport.cmd_verify(A(dp="360x780", serial=None)), expect_exit=1))
dev = FakeDevice(phys_size=(1080, 2340), phys_den=480)
results.append(scenario("verify 360x780dp == 기대 — 통과", dev,
                        lambda: viewport.cmd_verify(A(dp="360x780", serial=None))))

# reset — Override 가 사라져야 (#181 검증법 5: 사용자 기기 상태를 남기지 않음)
dev = FakeDevice(ov_size=(1080, 2340), ov_den=480)
results.append(scenario("reset — Override 제거", dev, lambda: viewport.cmd_reset(A(serial=None))))
assert dev.ov_size is None and dev.ov_den is None, "reset 후에도 Override 가 남았다"

# 프레임버퍼 지연 — wm 은 즉시 OK 인데 화면이 아직 안 바뀐 경우 (실기 실측 ~1.0s)
# apply 는 실제 캡처가 목표 크기가 될 때까지 기다려야 하고, 그 전에 성공을 보고하면 안 된다.
dev = FakeDevice(fb_lag_polls=4)
results.append(scenario("프레임버퍼 4폴링 지연 — 기다린 뒤 성공", dev,
                        lambda: viewport.cmd_apply(A(dp="360x780", k=None, freeze=False, theme=None, serial=None))))
assert dev.fb == (1080, 2340), f"대기 후에도 프레임버퍼가 {dev.fb} 다"

# 프레임버퍼가 끝까지 안 바뀌는 경우 — wm 은 OK 를 주지만 캡처는 이전 크기다 → 중단해야
dev = FakeDevice(fb_lag_polls=None)
viewport.SETTLE_TIMEOUT_S = 0.05          # 테스트에서 타임아웃을 짧게
results.append(scenario("wm 은 OK 인데 화면이 안 바뀜 — 중단해야 (조용한 통과 금지)", dev,
                        lambda: viewport.cmd_apply(A(dp="360x780", k=None, freeze=False, theme=None, serial=None)),
                        expect_exit=1))
viewport.SETTLE_TIMEOUT_S = 15.0

# verify — wm 보고와 실제 캡처가 다르면 중단해야 (리사이즈 진행 중 상태의 캡처는 무효)
dev = FakeDevice(ov_size=(1080, 2340), ov_den=480, fb_lag_polls=None)
dev.fb = (1080, 2400)                     # 화면은 아직 예전 크기
results.append(scenario("verify wm≠screencap — 중단해야", dev,
                        lambda: viewport.cmd_verify(A(dp="360x780", serial=None)), expect_exit=1))

# --freeze/--theme — dp 외 변수 고정 **과 원복**.
# 실측에서 여기가 새고 있었다: freeze 는 애니메이션을 0 으로 덮어쓰는데 reset 은 wm 만 되돌려서,
# 루프가 끝난 뒤에도 사용자 기기에 `window_animation_scale=0` 이 남았다. 원복까지 한 왕복으로 검사한다.
os.environ["XDG_CACHE_HOME"] = os.path.abspath("vp_cache")
dev = FakeDevice()
CALLS = []
viewport.adb = dev.run
viewport.capture_size = dev.capture_size
before = dict(dev.settings), dev.night
viewport.cmd_apply(A(dp="360x780", k=None, freeze=True, theme="light", serial=None))
frozen = [c for c in CALLS if "settings put" in c]
print(f"\n### --freeze 고정 명령\n   {chr(10).join('   ' + c for c in frozen)}")
applied = (len(frozen) == 5 and dev.settings["global/window_animation_scale"] == "0"
           and dev.settings["secure/immersive_mode_confirmations"] == "confirmed"
           and dev.night == "no")
results.append(applied)
print(f"   → {'PASS' if applied else 'FAIL'} (font_scale + 애니메이션 3종 + 전체화면 안내 + 테마 light)")

viewport.cmd_reset(A(serial=None))
restored = (dev.settings == before[0] and dev.night == before[1])
print(f"\n### reset 원복\n   settings={dev.settings}\n   night={dev.night}")
results.append(restored)
print(f"   → {'PASS' if restored else 'FAIL (직전값으로 안 돌아옴: 기대 %s / %s)' % before}")

print(f"\n== {sum(results)}/{len(results)} PASS ==")
sys.exit(0 if all(results) else 1)
