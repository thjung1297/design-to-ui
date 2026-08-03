#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 종료 게이트 — blind-spot ledger 완비를 기계적으로 강제한다.

수렴(종료) 선언 전, design-qa가 작성한 ledger.json을 검사한다. 모든 blind-spot 카테고리가 판정(verdict)과
근거(evidence)를 갖춰야 PASS. 미실행 행이나 근거 없는 floor가 하나라도 있으면 FAIL → 종료 불가.
"metric이 낮으니 floor"라고 default하는 것을 산문 'must'가 아니라 게이트로 막는다.

ledger.json:
{
  "categories": {
    "glyph_map":    {"verdict": "pass|fixed|floor", "evidence": "<probe 출력/crop 경로 또는 수치>"},
    "glyph_weight": {...}, "color": {...}, "spread": {...}, "canvas_pos": {...}, "layout": {...}
  }
}
verdict: pass(원래 정합) | fixed(보정함) | floor(불가역 — 근거로 probe-clean 입증 필수)

usage: python3 ledger_gate.py <ledger.json>   (exit 0=PASS, 1=FAIL)
"""
import json
import sys

REQUIRED = ["glyph_map", "glyph_weight", "color", "spread", "canvas_pos", "layout"]
VERDICTS = {"pass", "fixed", "floor"}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: ledger_gate.py <ledger.json>")
    try:
        cats = json.load(open(sys.argv[1])).get("categories", {})
    except Exception as e:
        print(f"FAIL — ledger.json 읽기 실패: {e}")
        sys.exit(1)

    fails = []
    for k in REQUIRED:
        e = cats.get(k)
        if not isinstance(e, dict):
            fails.append(f"{k}: 미실행 (ledger에 행 없음)")
            continue
        v = e.get("verdict")
        ev = str(e.get("evidence") or "").strip()
        if v not in VERDICTS:
            fails.append(f"{k}: verdict 누락/오류 ({v!r}, 허용 {sorted(VERDICTS)})")
        if not ev:
            fails.append(f"{k}: 근거(evidence) 없음 — '{v}' 선언 불가 (probe 출력/crop 경로 필요)")

    if fails:
        print("FAIL — 종료 불가:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print(f"PASS — {len(REQUIRED)}개 카테고리 전부 판정+근거 완비. 종료 가능.")
    sys.exit(0)


if __name__ == "__main__":
    main()
