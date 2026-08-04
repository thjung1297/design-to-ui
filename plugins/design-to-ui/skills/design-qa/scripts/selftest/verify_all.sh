#!/bin/bash
# design-qa 측정기 오프라인 셀프테스트 — 에뮬레이터·Figma 토큰·adb 불필요.
#
# 합성 픽스처로 "측정기가 이 오차를 잡는가"를 검사한다. 다루는 사각은 discussion #181(뷰포트 dp 불일치)·
# #186(얇은 옅은색 구분선 엣지)·#187(에셋 크기·probe 커버리지)에서 실측된 것들이고, 각 항목은 그 글들의
# "검증법" 중 **오프라인으로 가능한** 부분에 대응한다. 온디바이스 항목(실기기 3화면×3회, 세션 간 커버리지
# 재현성)은 여기서 못 재므로 포함하지 않는다.
#
# usage:  bash scripts/selftest/verify_all.sh          (통과 시 exit 0)
#         SKD=<design-qa 경로> bash verify_all.sh      (다른 체크아웃 대상 검사)
set -u
export PYTHONWARNINGS=ignore
WORK="$(cd "$(dirname "$0")" && pwd)"
export SKD="${SKD:-$(cd "$WORK/../.." && pwd)}"   # scripts/selftest → design-qa (heredoc 안 python 이 읽는다)
# 산출물은 임시 디렉터리에 — 레포를 더럽히지 않는다.
RUN="$(mktemp -d "${TMPDIR:-/tmp}/design-qa-selftest.XXXXXX")"
trap 'rm -rf "$RUN"' EXIT
cd "$RUN"
cp "$WORK/mkfix.py" "$WORK/meta_mcp.json" "$WORK/test_viewport.py" .
echo "SKD=$SKD"
echo "RUN=$RUN"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
# grep -q 로 기대 문자열 유무를 검사
expect()    { if echo "$2" | grep -q "$3"; then ok "$1"; else bad "$1 (기대: $3)"; fi }
expect_no() { if echo "$2" | grep -q "$3"; then bad "$1 (없어야 할 것: $3)"; else ok "$1"; fi }

python3 mkfix.py > /dev/null
DIV="divider:0,830,1080,850"
ICON="icon:75,1755,165,1845"

echo "════ #181 뷰포트 dp 정규화 ════"
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png o1 --rubric 2 \
      --figma-dp 360x780 --real-dp 411.43x914.29 2>&1)
expect "재현 상태(360dp figma vs 411dp 기기)에서 dp 게이트 FAIL" "$O" "dp 게이트 FAIL"
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png o2 --rubric 2 \
      --figma-dp 360x780 --real-dp 360x780 2>&1)
expect "정규화 후 dp 게이트 통과" "$O" "dp 게이트 OK"
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png o3 --rubric 2 2>&1)
expect "dp 미지정 시 not-checked 로 기록(조용히 통과 금지)" "$O" "not-checked"
O=$(python3 "$SKD/scripts/viewport.py" plan 375.5x813 2>&1)
expect "반정수 dp 프레임도 정수 px 로 계획(375.5→k=2)" "$O" "wm size 751x1626"
O=$(python3 "$SKD/scripts/crop.py" auto fix1_real.png fix1_figma.png c.png 2>&1)
expect_no "dp 맞는 입력에서 auto 억지정합 경고 없음(오탐)" "$O" "억지 정합"
O=$(SKD="$SKD" python3 test_viewport.py 2>&1 | tail -1)
expect "viewport 사다리·원복·freeze/theme·프레임버퍼 지연 분기 (가짜 adb)" "$O" "11/11 PASS"

echo "════ #186 엣지·full-bleed ════"
O=$(python3 "$SKD/scripts/edge_probe.py" fix1_figma.png fix1_real.png --regions "$DIV" --scale 3 2>&1)
expect "재현 케이스 FLAG" "$O" "EDGE MISMATCH"
expect "오차를 dp 로 정확히 지목(+16.00dp)" "$O" "+16.00dp"
for b in 0.4 1.2 2.0; do
  O=$(python3 "$SKD/scripts/edge_probe.py" g_figma.png g_real_$b.png --regions "$DIV" --scale 3 2>&1)
  expect "golden blur=$b 오탐 없음" "$O" "엣지·full-bleed OK"
done
python3 - <<'PY' > /dev/null
from PIL import Image, ImageFilter
for s, d in (("fix1_figma.png","d_figma.png"), ("fix1_real.png","d_real.png"), ("g_figma.png","dg_figma.png")):
    Image.open(s).point(lambda v: 255 - v).save(d)
Image.open("dg_figma.png").filter(ImageFilter.GaussianBlur(1.2)).save("dg_real.png")
PY
O=$(python3 "$SKD/scripts/edge_probe.py" d_figma.png d_real.png --regions "$DIV" --scale 3 --mode light 2>&1)
expect "다크 모드 재현 FLAG (--mode light)" "$O" "EDGE MISMATCH"
O=$(python3 "$SKD/scripts/edge_probe.py" dg_figma.png dg_real.png --regions "$DIV" --scale 3 --mode light 2>&1)
expect "다크 모드 golden 오탐 없음" "$O" "엣지·full-bleed OK"
O=$(python3 "$SKD/scripts/edge_probe.py" fix1_figma.png fix1_real.png --regions "empty:0,2200,200,2220" --scale 3 2>&1; echo "rc=$?")
expect "선 없는 박스를 SKIP 으로 드러냄(조용히 pass 금지)" "$O" "SKIP"
expect "SKIP 이 있으면 비정상 종료" "$O" "rc=2"
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png o4 --rubric 2 2>&1)
expect "metrics 에 pct_over_32 임계 기록" "$O" '"pct_over_32_threshold": 32'
expect "metrics 에 못 보는 것 명시" "$O" "옅은색 구분선"

echo "════ #187 에셋 크기·열거 ════"
O=$(python3 "$SKD/scripts/glyph_id_probe.py" fix2_figma.png fix2_real.png --regions "$ICON" \
      --size-check --scale 3 2>&1)
expect "10% 축소 FLAG (IoU 1.00 이어도)" "$O" "ASSET SIZE"
expect "IoU 는 여전히 1.00 (크기와 분리)" "$O" "IoU=1.00"
for dp in 19 18 17; do
  O=$(python3 "$SKD/scripts/glyph_id_probe.py" fix2_figma.png fix2_real_${dp}dp.png --regions "$ICON" \
        --size-check --scale 3 2>&1)
  expect "경계 곡선 real=${dp}dp FLAG" "$O" "ASSET SIZE"
done
for b in 0.4 1.2 2.0; do
  O=$(python3 "$SKD/scripts/glyph_id_probe.py" g_figma.png g_real_$b.png --regions "$ICON" \
        --size-check --scale 3 2>&1)
  expect "golden blur=$b 크기 오탐 없음" "$O" "에셋 크기 OK"
done
O=$(python3 "$SKD/scripts/glyph_id_probe.py" fix2_figma.png fix2_real.png --regions "$ICON" 2>&1)
expect "size-check 미지정 시 경고 문구" "$O" "size-check OFF"
# 열거: 결정성 + REST 래핑 동등성
python3 -c "
import json; d=json.load(open('meta_mcp.json'))
json.dump({'nodes':{'122:533':{'document':d}}}, open('meta_rest.json','w'))"
H1=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.json --scale 3 | shasum)
DET=ok; for i in 1 2 3 4 5; do
  H=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.json --scale 3 | shasum)
  [ "$H" = "$H1" ] || DET=bad
done
[ "$DET" = ok ] && ok "열거 결정성 5/5 동일 (세션 간 커버리지 편차 제거)" || bad "열거 결정성"
A=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.json  --scale 3 --emit glyph)
B=$(python3 "$SKD/scripts/enumerate_regions.py" meta_rest.json --scale 3 --emit glyph)
[ "$A" = "$B" ] && ok "MCP·REST 응답 형태 동등" || bad "MCP·REST 동등성 ($A vs $B)"
O=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.json --scale 3 2>&1)
expect "얇은 full-width 노드를 edge 로 열거" "$O" '"edge": "Divider'
expect "48dp 초과 INSTANCE 는 아이콘에서 제외" "$O" '"glyph": 2'
expect_no "visible:false 노드 제외" "$O" "Hidden thing"
expect_no "프레임 밖 노드 제외" "$O" "another frame"
expect "프레임 dp·기대 캡처 px 산출" "$O" '"expect_capture_px"'
G=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.json --scale 3 --emit glyph)
O=$(python3 "$SKD/scripts/glyph_id_probe.py" fix2_figma.png fix2_real.png --regions "$G" \
      --size-check --scale 3 2>&1)
expect "열거→probe 파이프에서 크기 오차 검출" "$O" "ASSET SIZE"

echo "════ extent·resize 게이트 (판정이 정답과 반대로 움직이는 자리) ════"
O=$(python3 "$SKD/scripts/overlay.py" e_figma.png e_real_ok.png oe1 --rubric 2 \
      --figma-dp 393x852 --real-dp 393x852 2>&1; echo "rc=$?")
expect "dp 게이트는 통과하는데 extent 게이트가 잡는다" "$O" "extent 게이트 FAIL"
expect "extent 불일치면 비정상 종료" "$O" "rc=1"
expect "resize 로 흡수하지 말고 재캡처/재crop 하라고 지시" "$O" "다시 잡거나"
expect "하단 앵커는 dp 절대 probe 로 넘기라고 지시" "$O" "dp 절대 probe"
# 강행 시에는 순위가 실제로 뒤집히는 것을 회귀로 고정한다 (정합본 > 오차본)
# 강행 시 stdout 앞에 경고문이 붙으므로 metrics.json 파일에서 읽는다.
python3 "$SKD/scripts/overlay.py" e_figma.png e_real_ok.png  oe2 --rubric 2 --allow-extent-mismatch >/dev/null 2>&1
python3 "$SKD/scripts/overlay.py" e_figma.png e_real_bad.png oe3 --rubric 2 --allow-extent-mismatch >/dev/null 2>&1
MOK=$(python3 -c "import json;print(json.load(open('oe2/metrics.json'))['mean_diff'])")
MBAD=$(python3 -c "import json;print(json.load(open('oe3/metrics.json'))['mean_diff'])")
if python3 -c "import sys; sys.exit(0 if $MOK > $MBAD else 1)"; then
  ok "강행하면 정합본($MOK) > 오차본($MBAD) 로 순위가 뒤집힘 — 게이트가 필요한 이유"
else
  bad "순위 반전이 재현되지 않음 (정합본 $MOK / 오차본 $MBAD) — 픽스처 확인"
fi
O=$(python3 "$SKD/scripts/overlay.py" e_figma.png e_real_ok.png oe4 --rubric 2 --allow-extent-mismatch 2>&1)
expect "강행도 metrics 에 mismatch-forced 로 남김" "$O" "mismatch-forced"
# 비균일 resize 게이트 — 같은 크기 페어에서는 오탐 없어야 한다
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png oe5 --rubric 2 2>&1)
expect_no "같은 크기 페어에서 extent/resize 게이트 오탐 없음" "$O" "게이트 FAIL"
expect "resize 게이트 결과를 metrics 에 기록" "$O" '"resize_gate"'
# 출력이 입력을 덮어쓰는 것 차단
mkdir -p ow && cp fix1_figma.png ow/figma.png && cp fix1_real.png ow/real.png
O=$(python3 "$SKD/scripts/overlay.py" ow/figma.png ow/real.png ow --rubric 2 2>&1)
expect "outdir 를 입력 디렉터리로 주면 거부 (입력 파괴 방지)" "$O" "산출물이 입력을 덮어쓴다"

echo "════ 실기 실측에서 나온 케이스 ════"
# (a) 투명 라운드 코너 — 코너가 검정이 되어 max_diff 를 채우면 안 된다
O=$(python3 "$SKD/scripts/overlay.py" t_figma_rgba.png t_real_opaque.png ot --rubric 2 2>&1)
expect "투명 코너를 통계에서 제외" "$O" '"figma_alpha_excluded_px"'
MX=$(echo "$O" | python3 -c "import sys,json;print(json.load(sys.stdin)['max_diff'])")
if [ "$MX" -le 32 ]; then ok "투명 코너가 max_diff 를 오염시키지 않음 (max_diff=$MX)"
else bad "투명 코너 아티팩트가 남음 (max_diff=$MX — 코너 검정 변환 의심)"; fi
O=$(python3 "$SKD/scripts/crop.py" box t_real_opaque.png /dev/null --box 0,0,1080,2340 --figma t_figma_rgba.png 2>&1)
expect_no "crop 정합 게이트가 투명 코너에 끌리지 않음" "$O" "오프셋 의심"
# (b) 저대비 아이콘 — 절대 ink 임계로는 0px 라 skip 되던 케이스
O=$(python3 "$SKD/scripts/glyph_id_probe.py" p_figma.png p_real.png \
      --regions "pale:96,1740,144,1860" --size-check --scale 3 2>&1)
expect "저대비 아이콘을 중간 레벨로 재측정 (skip 하지 않음)" "$O" "저대비 — 중간 레벨로 재측정"
expect "저대비 아이콘의 크기 오차도 잡음" "$O" "ASSET SIZE"
expect "저대비 아이콘이 coverage 에 집계됨" "$O" "coverage probed=1"
# (c) MCP get_metadata XML — 상대좌표 누적 + 태그명 타입 + 뒤에 붙은 안내문
O=$(python3 "$SKD/scripts/enumerate_regions.py" meta_mcp.xml --scale 3 2>&1)
expect "MCP XML 파싱 (안내문 꼬리 포함)" "$O" '"expect_capture_px"'
expect "XML 상대좌표 누적 — CheckIcon 절대 위치" "$O" 'CheckIcon:'
expect "XML 태그명 → 타입 (rectangle 이 edge 로)" "$O" '"edge": "Divider'
expect "boolean-operation 내부 벡터는 중복 열거 안 함" "$O" '"glyph": 1'
expect_no "boolean-op 자식(part-a)이 region 에 안 들어감" "$O" "part-a"
# (d) glyph region 에 배경 여유가 붙는가 (타이트 bbox 는 배경 추정을 무너뜨린다)
python3 - <<'PY'
import json, subprocess, sys, os
skd = os.environ["SKD"]
d = json.loads(subprocess.run([sys.executable, f"{skd}/scripts/enumerate_regions.py",
                               "meta_mcp.xml", "--scale", "3"], capture_output=True, text=True).stdout)
g = d["nodes"]["glyph"][0]
box, tight = g["box"], g["tight_box"]
assert box[0] < tight[0] and box[2] > tight[2], f"여유 없음 box={box} tight={tight}"
print("OK margin", box, tight)
PY
[ $? -eq 0 ] && ok "glyph region 에 배경 여유 + tight_box 병기" || bad "glyph region 여유"

echo "════ 개별 임계를 통과하는 오차 (실측 후속) ════"
# 실측: letterSpacing -0.5% 는 width_ratio 0.988, 한글 줄바꿈은 1.052 — 둘 다 ±12% 개별 임계를 통과했다.
GSR=$(cat gs_regions.txt)
O=$(python3 "$SKD/scripts/glyph_probe.py" gs_figma.png gs_real_sys.png --regions "$GSR" 2>&1)
expect "전역 폭 편차(letterSpacing급)를 잡는다" "$O" "전역 폭 편차"
expect "전역 편차는 픽셀이 아니라 선언값 대조로 보낸다" "$O" "style.letterSpacing"
expect "국소 이상치(줄바꿈급)를 잡는다" "$O" "OUTLIER"
expect_no "짧은 텍스트가 방향 일치 분모를 희석하지 않는다" "$O" "후보 0개"
O=$(python3 "$SKD/scripts/glyph_probe.py" gs_figma.png gs_real_ok.png --regions "$GSR" 2>&1)
expect "AA 수준 흔들림에는 오탐하지 않는다" "$O" "후보 0개"

echo "════ 잠든 기기 캡처 방어선 ════"
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["SKD"], "scripts"))
import capture
assert capture.uniform_color("solid_black.png") == (0, 0, 0), "단색 검정을 못 잡는다"
assert capture.uniform_color("fix1_figma.png") is None, "정상 캡처를 단색으로 오판한다"
assert capture.wakefulness.__doc__, "wakefulness 헬퍼가 없다"
PY
[ $? -eq 0 ] && ok "단색(검정) 캡처를 감지 · 정상 캡처는 통과" || bad "단색 캡처 방어선"

# 엉뚱한 화면은 단색 검사를 통과한다 — 실측: monkey 런치 실패로 런처 홈이 찍혔는데 dp·extent·resize 게이트가
# 전부 ok 이고 mean_diff 57.21 만 남았다. 그래서 "무엇이 포그라운드인지"를 직접 본다.
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["SKD"], "scripts"))
import capture
PKG = "com.example.sampleapp"
def focus_of(win):
    return lambda args, serial=None: f"  mCurrentFocus={win}\n"

capture._adb = focus_of(f"Window{{c9ee367 u0 {PKG}/{PKG}.MainActivity}}")
capture.ensure_focus(PKG)                      # 대상이 포그라운드 → 통과해야 한다

# 런처 홈 (실측 trap): 크기·단색 검사로는 구분되지 않는다
capture._adb = focus_of("Window{a73edbc u0 com.google.android.apps.nexuslauncher/"
                        "com.google.android.apps.nexuslauncher.NexusLauncherActivity}")
try:
    capture.ensure_focus(PKG)
    raise AssertionError("런처 홈 포그라운드를 통과시켰다 — 엉뚱한 화면이 전 게이트를 통과한다")
except SystemExit:
    pass

# 포커스를 못 읽는 상태도 '모르는 것'이지 '정합'이 아니다 → 멈춰야 한다
capture._adb = lambda args, serial=None: "mCurrentFocus=null\n"
try:
    capture.ensure_focus(PKG)
    raise AssertionError("mCurrentFocus=null 을 통과시켰다")
except SystemExit:
    pass
PY
[ $? -eq 0 ] && ok "포그라운드 검증: 대상 통과 · 런처 홈/null 차단" || bad "포그라운드 검증 방어선"

# 멀티 디스플레이: "첫 번째"가 아니라 **wm 보고와 크기가 일치하는** 디스플레이를 골라야 한다.
# 실측(REAR_DISPLAY_MODE): EMU_display_0=1080x2400 인데 정규화한 1080x2340 은 EMU_display_1 에 걸렸다 —
# 첫 id 를 찍으면 정규화하지 않은 화면을 대조하게 된다.
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["SKD"], "scripts"))
import capture
capture.display_ids = lambda serial=None: ["dispA", "dispB"]
capture.wm_size = lambda serial=None: (1080, 2340)
capture._cap_size = lambda serial, d: {"dispA": (1080, 2400), "dispB": (1080, 2340)}[d]
capture._DISPLAY_CACHE.clear()
got = capture.screencap_args("emu-x")
assert got == ["-d", "dispB"], f"wm 과 일치하는 디스플레이를 안 골랐다: {got}"
assert capture.screencap_args("emu-x", display="dispA") == ["-d", "dispA"], "명시 지정이 무시됐다"
# 리사이즈 대기 중(아무 디스플레이도 아직 목표 크기가 아님) → 첫 id 로 두어 호출자의 대기가 동작해야 한다
capture._DISPLAY_CACHE.clear()
capture.wm_size = lambda serial=None: (1080, 9999)
assert capture.screencap_args("emu-x") == ["-d", "dispA"], "대기 중 fallback 이 아니다"
# 단일 디스플레이면 -d 를 붙이지 않는다 (기존 기기 회귀)
capture.display_ids = lambda serial=None: ["only"]
assert capture.screencap_args("emu-y") == [], "단일 디스플레이에 -d 를 붙였다"
PY
[ $? -eq 0 ] && ok "멀티 디스플레이에서 wm 과 일치하는 화면 선택 (첫 id 아님)" || bad "디스플레이 선택"

echo "════ 기기 상태 원복 (freeze/theme) ════"
python3 - <<'PY'
import os, sys, json
sys.path.insert(0, os.path.join(os.environ["SKD"], "scripts"))
os.environ["XDG_CACHE_HOME"] = os.path.abspath("cache")
import viewport
# `cmd uimode night` 출력에서 값만 뽑는다 — 값만 주는 read 명령이 없다.
assert viewport.parse_night("Night mode: no") == "no"
assert viewport.parse_night("Night mode: yes\n") == "yes"
assert viewport.parse_night("garbage") is None
# 저장/복원 왕복 — 직전값이 없던 설정(None)도 그대로 보존돼야 delete 로 되돌릴 수 있다.
p = viewport.state_path("emulator-x")
viewport._save_state("emulator-x", {"settings": {"global/window_animation_scale": "1.0",
                                                 "system/font_scale": None},
                                    "uimode_night": "yes"})
got = viewport._load_state("emulator-x")
assert got["settings"]["global/window_animation_scale"] == "1.0", got
assert got["settings"]["system/font_scale"] is None, got
assert got["uimode_night"] == "yes", got
assert "emulator-x" in p, p
PY
[ $? -eq 0 ] && ok "freeze/theme 직전값 저장·복원 왕복 + night 파싱" || bad "기기 상태 원복"

echo "════ 종료 게이트 ════"
python3 - <<'PY' > /dev/null
import json
rows6 = ["glyph_map","glyph_weight","color","spread","canvas_pos","layout"]
rows8 = ["glyph_map","asset_size","edge"] + rows6[1:]
json.dump({"categories":{k:{"verdict":"pass","evidence":"probe out"} for k in rows6}}, open("l_old.json","w"))
json.dump({"categories":{k:{"verdict":"pass","evidence":"probe out"} for k in rows8}}, open("l_nocov.json","w"))
p={"categories":{k:{"verdict":"pass","evidence":"probe out"} for k in rows8}}
p["categories"]["glyph_map"]["coverage"]={"enumerated":3,"probed":1}
p["categories"]["asset_size"]["coverage"]={"enumerated":3,"probed":3}
p["categories"]["edge"]["coverage"]={"enumerated":2,"probed":2}
json.dump(p, open("l_partial.json","w"))
f=json.loads(json.dumps(p)); f["categories"]["glyph_map"]["coverage"]={"enumerated":3,"probed":3}
json.dump(f, open("l_full.json","w"))
PY
O=$(python3 "$SKD/scripts/ledger_gate.py" l_old.json 2>&1)
expect "구 6행 ledger → asset_size 미실행으로 FAIL" "$O" "asset_size: 미실행"
expect "구 6행 ledger → edge 미실행으로 FAIL" "$O" "edge: 미실행"
O=$(python3 "$SKD/scripts/ledger_gate.py" l_nocov.json 2>&1)
expect "coverage 없으면 FAIL" "$O" "coverage 없음"
O=$(python3 "$SKD/scripts/ledger_gate.py" l_partial.json 2>&1)
expect "열거 3 중 1 검사 → 커버리지 미달 FAIL" "$O" "커버리지 미달"
O=$(python3 "$SKD/scripts/ledger_gate.py" l_full.json 2>&1)
expect "8행 + 커버리지 완비 → PASS" "$O" "PASS — 8개 카테고리"

# blocked: Figma 선언값이 갈려 정답이 없는 행. 종료는 되지만 조용히 삼켜지면 floor 와 구별되지 않는다.
python3 - <<'PY' > /dev/null
import json
f = json.load(open("l_full.json"))
f["categories"]["spread"] = {"verdict": "blocked",
                             "evidence": "TrackList itemSpacing 122:544=12dp vs 100:344=20dp"}
json.dump(f, open("l_blocked.json", "w"))
n = json.loads(json.dumps(f)); n["categories"]["spread"]["evidence"] = ""
json.dump(n, open("l_blocked_noev.json", "w"))
PY
O=$(python3 "$SKD/scripts/ledger_gate.py" l_blocked.json 2>&1)
expect "blocked 는 종료 가능 (PASS)" "$O" "PASS — 8개 카테고리"
expect "blocked 행을 사용자 전달용으로 따로 찍는다" "$O" "사용자 결정이 필요한 행 1개"
O=$(python3 "$SKD/scripts/ledger_gate.py" l_blocked_noev.json 2>&1)
expect "근거 없는 blocked 는 FAIL" "$O" "근거(evidence) 없음"

echo "════ 회귀 ════"
O=$(python3 "$SKD/scripts/selftest_crop.py" 2>&1 | tail -1)
expect "crop.py selftest 9/9 유지" "$O" "9/9 PASS"
O=$(python3 "$SKD/scripts/overlay.py" fix1_figma.png fix1_real.png o5 --blend-only 2>&1)
expect "overlay --blend-only 기존 동작 유지" "$O" "blend50.png"
O=$(python3 "$SKD/scripts/glyph_probe.py" fix2_figma.png fix2_real.png --regions "$ICON" 2>&1)
expect "glyph_probe 무수정 동작 유지" "$O" "width_ratio=0.902"
O=$(python3 "$SKD/scripts/align_probe.py" fix1_figma.png fix1_real.png --grid 6,4 --range 20 --thr 4 2>&1)
expect "align_probe 무수정 동작 유지" "$O" "drift 후보 0개"


# 스킬의 실행 전제는 "python3 + Pillow" 뿐이라 사용자의 python3 이 macOS 시스템 3.9 일 수 있다.
# `str | None`(PEP 604) 은 3.9 에서 def 시점에 TypeError 로 죽으므로 전 스크립트가 기동되는지 본다.
# OLDPY 를 지정하면 그 인터프리터로 검사한다 (없으면 이 섹션 skip).
OLDPY="${OLDPY:-/usr/bin/python3}"
if [ -x "$OLDPY" ] && "$OLDPY" -c "import PIL" 2>/dev/null; then
  echo "════ 구 파이썬 호환 ($("$OLDPY" -V 2>&1)) ════"
  for f in crop.py capture.py overlay.py edge_probe.py enumerate_regions.py viewport.py \
           glyph_id_probe.py glyph_probe.py align_probe.py color_probe.py ledger_gate.py trim.py; do
    O=$("$OLDPY" "$SKD/scripts/$f" --help 2>&1 | head -3)
    expect_no "$f --help 크래시 없음" "$O" "Traceback"
  done
  O=$("$OLDPY" "$SKD/scripts/selftest_crop.py" 2>&1 | tail -1)
  expect "crop selftest 9/9" "$O" "9/9 PASS"
else
  echo "════ 구 파이썬 호환 — skip ($OLDPY 없음 또는 Pillow 미설치) ════"
fi

echo
echo "════════════════════════════════"
echo "  PASS $PASS / FAIL $FAIL"
echo "════════════════════════════════"
[ "$FAIL" -eq 0 ]
