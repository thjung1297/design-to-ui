#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""design-qa: 종료 게이트 — blind-spot ledger 완비를 기계적으로 강제한다.

수렴(종료) 선언 전, design-qa가 작성한 ledger.json을 검사한다. 모든 blind-spot 카테고리가 판정(verdict)과
근거(evidence)를 갖춰야 PASS. 미실행 행이나 근거 없는 floor가 하나라도 있으면 FAIL → 종료 불가.
"metric이 낮으니 floor"라고 default하는 것을 산문 'must'가 아니라 게이트로 막는다.

**커버리지도 본다(열거 대비 검사 수).** verdict·evidence 문자열만 보던 때는 화면에 아이콘이 3개인데 1개만
검사해도 PASS 였다 — 검사 대상(region)을 사람이 정했으므로 세션마다 커버리지가 달라졌다. `enumerate_regions.py`
가 열거한 수를 `coverage.enumerated` 에, 실제 probe 한 수를 `coverage.probed` 에 적고, probed < enumerated 면
FAIL 한다. 열거 기반 행(`COVERAGE_REQUIRED`)은 이 필드가 **필수**다.

ledger.json:
{
  "categories": {
    "glyph_map":    {"verdict": "pass|fixed|floor", "evidence": "<probe 출력/crop 경로 또는 수치>",
                     "coverage": {"enumerated": 3, "probed": 3}},
    "asset_size":   {"verdict": ..., "evidence": "glyph_id_probe --size-check 출력", "coverage": {...}},
    "edge":         {"verdict": ..., "evidence": "edge_probe 출력",                  "coverage": {...}},
    "glyph_weight": {...}, "color": {...}, "spread": {...}, "canvas_pos": {...}, "layout": {...}
  }
}
verdict: pass(원래 정합) | fixed(보정함) | floor(불가역 — 근거로 probe-clean 입증 필수)
       | blocked(오차는 확정, 코드로는 못 고침 — Figma 선언값이 프레임끼리 갈려 정답이 없다)

blocked 는 floor 와 다르다 — floor 는 "잔차가 불가역", blocked 는 "정답값을 디자인 쪽이 정해야 한다".
실측: TrackList itemSpacing 이 122:544·109:455·2001:15 = 12dp, 100:344·109:126·122:574 = 20dp 로 갈려
어느 값으로 바꿔도 나머지 3장이 어긋난다. floor 로 적으면 거짓이고 fixed 로 적으면 값이 왕복한다.
도피구가 되지 않도록 게이트가 blocked 행을 PASS 출력에 따로 찍는다. evidence 에는 충돌하는 선언값과
노드 id 를 두 개 이상 적는다.

usage: python3 ledger_gate.py <ledger.json>   (exit 0=PASS, 1=FAIL)
"""
import json
import sys

# 검사(instrument)가 있는 blind-spot 카테고리. 행이 없으면 '미실행'이라 종료 불가.
REQUIRED = [
    "glyph_map",      # glyph_id_probe IoU (모양)
    "asset_size",     # glyph_id_probe --size-check (크기 — IoU 는 크기를 정규화로 지운다)
    "edge",           # edge_probe (full-bleed·구분선 — 면적 평균이 원리적으로 못 보는 카테고리)
    "glyph_weight",
    "color",
    "spread",
    "canvas_pos",
    "layout",
]
# 검사 대상을 Figma 노드에서 열거하는 행 — 커버리지(열거 수 대비 검사 수)를 반드시 적어야 한다.
COVERAGE_REQUIRED = ["glyph_map", "asset_size", "edge"]
VERDICTS = {"pass", "fixed", "floor", "blocked"}


def check_coverage(key, entry, fails):
    cov = entry.get("coverage")
    required = key in COVERAGE_REQUIRED
    if cov is None:
        if required:
            fails.append(f"{key}: coverage 없음 — enumerate_regions.py 열거 수와 검사 수를 "
                         f'{{"enumerated": N, "probed": M}} 로 적을 것 (1/3만 검사해도 PASS 되는 구멍 차단)')
        return
    if not isinstance(cov, dict):
        fails.append(f"{key}: coverage 형식 오류 ({cov!r}) — {{'enumerated': N, 'probed': M}} 필요")
        return
    try:
        enum_n, probed_n = int(cov["enumerated"]), int(cov["probed"])
    except (KeyError, TypeError, ValueError):
        fails.append(f"{key}: coverage 에 enumerated/probed 정수가 필요 ({cov!r})")
        return
    if enum_n < 0 or probed_n < 0:
        fails.append(f"{key}: coverage 음수 ({cov!r})")
        return
    if probed_n < enum_n:
        fails.append(f"{key}: 커버리지 미달 — 열거 {enum_n}개 중 {probed_n}개만 검사 "
                     f"(빠진 {enum_n - probed_n}개는 '검사 안 함'이지 '정합'이 아니다)")


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
        check_coverage(k, e, fails)

    if fails:
        print("FAIL — 종료 불가:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    covered = ", ".join(f"{k}={cats[k]['coverage']['probed']}/{cats[k]['coverage']['enumerated']}"
                        for k in COVERAGE_REQUIRED)
    print(f"PASS — {len(REQUIRED)}개 카테고리 전부 판정+근거 완비. 커버리지 {covered}. 종료 가능.")
    # 조용히 삼키면 floor 와 구별되지 않으므로 종료 출력에서 따로 찍는다.
    blocked = [(k, str(cats[k].get("evidence") or "").strip())
               for k in REQUIRED if cats[k].get("verdict") == "blocked"]
    if blocked:
        print(f"\n사용자 결정이 필요한 행 {len(blocked)}개 — 반드시 사용자에게 전달할 것:")
        for k, ev in blocked:
            print(f"  - {k}: {ev}")
    sys.exit(0)


if __name__ == "__main__":
    main()
