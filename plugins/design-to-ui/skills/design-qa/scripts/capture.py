#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 실기기/에뮬레이터 풀스크린 캡처.

adb exec-out screencap 으로 PNG 를 받아 저장한다. 인프라 0 — 빌드된 앱 + adb 만 필요.

usage:
    python3 capture.py <out.png> [--serial <adb-serial>]
"""
import argparse
import subprocess
import sys


def capture(out_path: str, serial: str | None = None) -> None:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["exec-out", "screencap", "-p"]
    png = subprocess.run(cmd, capture_output=True).stdout
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit("capture failed — adb 연결/기기 상태 확인 (PNG 시그니처 없음)")
    with open(out_path, "wb") as f:
        f.write(png)
    print(f"captured {len(png)} bytes -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--serial", default=None)
    a = ap.parse_args()
    capture(a.out, a.serial)
