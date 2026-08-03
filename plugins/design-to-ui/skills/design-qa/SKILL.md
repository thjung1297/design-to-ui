---
name: design-qa
description: 빌드된 앱 화면을 실기기/시뮬레이터에서 캡처해 Figma 원본과 오버레이(50% 블렌드 + diff 히트맵 + figma|real 나란히 크롭 + 픽셀색 비교)로 대조하고, 코드 오차로 확정된 항목을 Figma 선언값으로 되짚어 스스로 보정하는 검증 루프. 비교·측정 엔진은 플랫폼 중립이고 캡처 계층만 플랫폼별이다(Android·iOS·Web 지원). 두 진입: ① codegen Step 7c 위임 호출, ② 직접 호출(/design-qa) — 프롬프트로 검증/보정 모드를 판별하고 Figma 링크 해소·현재 브랜치 빌드·캡처까지 스스로 오케스트레이션. "오버레이 검증", "실기기 대조", "figma랑 겹쳐봐", "design-qa", "어디가 틀렸는지 보정", "Step 7c" 같은 요청에 사용.
license: Apache-2.0
metadata:
  author: NAVER
  version: "3.3"
  platform: [android, ios, web]
---

# design-qa — 오버레이 검증 루프

codegen의 "LLM 눈대중 대조"를 **실기기/시뮬레이터 런타임에서 수치로** 수행하는 보완 트랙이다. JVM
(layoutlib) 정량 트랙과 달리 **실 렌더엔진·다크모드·디바이스 density**가 그대로 반영된다 — 둘은 경쟁이
아니라 병행이다.

**비교·측정 엔진(overlay·align_probe·glyph_probe)과 crop 의 `auto`/`box`/`anchor`/정합 게이트는 플랫폼 중립이다.
플랫폼에 종속되는 건 캡처와 dumpsys `frame` crop, "고치는 법(코드 어휘)"뿐**이다. 그래서 이 문서는 루프·판정·종료 계약을 중립으로 기술하고,
플랫폼별 명령·보정 어휘는 `references/<platform>.md`로 분리한다(`android.md`, `ios.md`, `web.md`).

## 두 진입 — 빌드·진입·캡처는 공유

목표는 **인간 개입 최소화** 자율 검증이다. 빌드·화면 진입·캡처는 진입과 무관하게 design-qa가 스스로 한다.
두 진입은 *앞단 입력을 어떻게 얻느냐*만 다르다.

- **위임 진입** (codegen Step 7c): `file_key`·`node_id`·crop 인자 + 빌드/실행 정보가 넘어옴 →
  0단계 건너뛰고 "빌드·화면 진입"부터 자율 수행.
- **직접 진입** (`/design-qa <프롬프트>`): 입력이 자연어뿐 → 0단계(입력 해소)로 모드·링크를 먼저 정한 뒤 합류.

## 0단계 — 입력 해소 (직접 진입 전용)

**0a. 모드 판별. 기본값은 보정 모드(자율 루프).**
- 인자 없는 `/design-qa` 또는 애매한 프롬프트 → **보정 모드**: 검증→보정→재빌드→최종 오버레이까지 묻지 않고 자동.
- 오차 서술("틀렸/밀렸/색이/폰트/위치/간격/크기가 …")이 있으면 → **보정 모드**, 그 영역 우선 조준.
- "오버레이만/겹쳐봐/확인만" 신호가 명시되면 → **검증 모드**(blend-only 표시, 코드 미수정).

**0b. Figma 링크 해소.** ① 프롬프트의 URL → ② 없으면 **세션 직전 링크 재사용** → ③ 둘 다 없을 때만 요청.
확보한 URL의 `file_key`·`node_id`를 추출하고 **세션에 유지**해 후속 호출이 ②로 재사용하게 한다.

## 빌드·화면 진입 (양 진입 공유, 자율)

- **빌드:** 타겟 앱을 **지금 체크아웃된 브랜치 그대로** 빌드한다(보정 루프의 코드 수정도 현재 트리에 적용 후 재빌드).
- **화면 진입 + 캡처 fallback (인간 개입은 최후수단):** 대상 화면 포그라운드 진입을 자동 시도한다. 자율 진입이
  끝까지 막힐 때(프로젝트 의존 로그인 등)**에만** 안내 후 사용자 신호를 받아 캡처한다 — 성공하면 신호 없이 진행.

**산출물 위치(outdir) — 기본은 Desktop.** 기본 outdir는 `$HOME/Desktop/design-qa/{검수화면}/`(예:
`$HOME/Desktop/design-qa/날씨-엔드/`)이고, 캡처·크롭 중간물도 같은 디렉터리에 둔다. `{검수화면}`은 node id가
아니라 **사람이 알아보는 화면 이름**(figma 프레임명 등, 공백은 `-`)으로 쓴다 — Desktop에 폴더가 쌓였을 때 어느
검수 결과인지 이름만으로 구분돼야 한다. 이 루프의 마지막 동작이 "사람이 이미지를 눈으로 확인"이라서 산출물은
Finder에서 바로 열리는 자리에 있어야 한다 — `/tmp`는 사용자가 찾아가기 어렵고 정리·재부팅으로 사라진다.
사용자가 경로를 명시하면 그 경로를 따른다.

**마무리는 호출 종류로 갈린다:**
- **직접/자율 호출:** 수렴 후 outdir를 **`blend50.png` 한 장만 남기고 정리** → `open`으로 띄우고 종료. 사람은 이미지 한 장만 본다.
- **위임 보정:** full rubric 산출물 + `OVERLAY-REPORT.md`를 **유지**(위임자가 코드 오차 리스트·리포트 경로를 소비). `open` 불필요.

## 플랫폼 캡처 계층 (유일한 플랫폼 종속)

캡처와 exact-crop만 플랫폼별 구현이다(측정·비교는 중립). 플랫폼은 0단계/위임 인자로 판별한다.

- **Android** → `references/android.md` (adb 캡처·dumpsys frame crop·Compose 보정 어휘)
- **iOS** → `references/ios.md` (simctl 캡처·시뮬레이터 bounds crop·SwiftUI/UIKit 보정 어휘)
- **Web** → `references/web.md` (Playwright Storybook 요소 캡처·`fonts.ready`·trim·CSS/React 보정 어휘·`run.mjs` node-map 오케스트레이션)

**exact-crop 원칙 (중립 — 이 루프의 핵심).** 풀스크린을 좌표 추측으로 자르면 ~15px 오프셋 artifact로 "틀어짐"
오판이 난다. 반드시 **대상 창의 실제 경계로 정확히 crop**한다. 창이 신뢰할 스크린 좌표를 안 주는 환경
(임베디드/멀티윈도 호스트 — dumpsys가 로컬좌표만 줌)에선 **수동 좌표 추측 금지**, figma 기준 래스터를 템플릿으로
위치를 자동 매칭하는 **content 기반 crop**(플랫폼 crop의 `auto`)을 쓴다. crop 후 두 게이트로 검산한다:
`overlay.py`의 `resize_ratio` — **양축이 같은 배율(예 `[3.0,3.0]`, iOS @3x 등)이면 density 정규화(정상, 왜곡 아님)**,
**두 축이 서로 다르면(예 `[1.0,0.94]`) 그 축에 stretch(환경 아티팩트)** → 판정에서 분리하고,
**전역 오프셋(dx,dy)이 임계(±3px) 초과면 crop 박스가 어긋난 것**(요소별 오차 아님) — crop을 다시 맞춘다.

## 워크플로우

1. **캡처** — 플랫폼 capture(→ references). 풀스크린 이미지.
2. **exact-crop** — 대상 창 실경계로. **임베디드/멀티윈도 호스트(dumpsys가 로컬좌표만)는 좌표 추측 금지 →
   중립 `crop.py auto <cap_full.png> figma.png <real.png>`**(figma 템플릿 content 매칭; 화면 density 달라도 스케일 후보 서치)라
   **Step 3(figma)을 먼저** 받아 넘긴다. 창이 실좌표를 주면 플랫폼 `frame`(→ references), 확정 박스 재사용은 `box`/`anchor` — 이 경우 `--figma`로 정합 게이트.
3. **Figma export** — figma-desktop MCP `get_screenshot(nodeId, fileKey, maxDimension=real 캡처 긴 변 이상)`
   반환 URL을 `curl -L -o figma.png` (기본 1024는 real 대비 upscale 흐림). scale은 `overlay.py`가 real 크기로 resize → density-match·토큰 불요.
4. **오버레이 + 판정** — `overlay.py figma.png real.png <outdir>`:
   - 검증 모드(빠른 표시): `--blend-only` → `blend50.png` 한 장, 이어서 `Read`로 표시.
   - 보정 모드(자율 루프): `--rubric 3 --grid 12,8 --top 6` → `metrics.json`·`cmp_*`로 진단.
5. **코드 보정** — 아래 판정·종료 계약으로 확정된 오차만 Figma 선언값으로 교체. 보정 후 2단계부터 재실행.
6. **리포트** — 위임 보정 전용(`OVERLAY-REPORT.md`). 직접/자율 호출은 리포트를 만들지 않는다.

## 판정 — pixel-subtract 단독 금지

diff metric은 **큰 면적·색차·평균**만 본다 → 작은 글리프, 통째 밀린 블록, 의미색, 분포(spread), 글자 폭/
weight, 스케일을 모두 놓친다. **metric이 낮을수록(정합처럼 보일수록) 이 사각이 floor에 그대로 남는다.**
그래서 metric과 **별개로** 아래를 매번 돌린다.

**A. 아티팩트 vs 코드 오차 분리 (먼저).** 다음만 불가역 floor 후보로 두고 나머지는 코드 오차 후보로:
- `resize_ratio` **양축 배율이 서로 다르면** → 패널 stretch(환경). 별도 기록. (양축 균일 배율은 density 정규화라 정상 — 왜곡 아님.)
- 전 글자에 **크기와 무관한 균일 ≤1px halo** → 렌더러 서브픽셀 AA.

**B. cmp 직독이 1차 진단.** blend/heatmap은 "어디를 볼지" 후보만 좁히는 보조. 최종 per-element 판정은
`cmp_*.png`(figma|real 나란히)를 **직접 보고** + `suspect_regions` 픽셀색(darkest/mean)을 Figma 기준값과 수치 비교로 한다.

## 종료 계약 — floor는 default가 아니라 *증명이 필요한 결론*

**핵심 규율: metric이 floor 밴드(텍스트 화면 ~1.5%, 아이콘·게이지·그래프 화면 ~2–3%)에 들어도 그건
"레이아웃 nudge를 멈출" 신호일 뿐 "끝"이 아니다.** 종료는 아래 **blind-spot ledger의 모든 행이 evidence와
함께 통과**할 때만 성립한다. 미실행 행이 하나라도 있으면 미종료다. 어떤 잔차를 "floor/AA"라 부르려면 **그
행의 probe가 clean**이어야 한다 — metric이 낮다는 이유로 floor라 default하지 말 것.

| blind-spot 카테고리 | 검사(instrument) | floor 선언 가능 조건 (evidence) |
|---|---|---|
| 글리프 매핑·형태 | `glyph_id_probe.py` 형태 IoU(모든 아이콘·소형 포함; 본체 자동 타이트닝) | IoU 임계 이상. 낮으면 **크롭 확인 후** 올바른 노드 재export(회전 대용 ❌) — 텍스트 인접 소형 글리프는 false-positive 주의 |
| 글자 폭·weight | `glyph_probe.py`로 텍스트 run figma vs real **advance/stroke 폭** | 폭 임계 내 일치 (어긋나면 faux-bold/letterSpacing) |
| 텍스트 의미색 | `color_probe.py`로 의미색 텍스트 대표색 vs figma 토큰 hex | 거리 임계 내 일치 |
| 분포(spread) | 행별 figma `layoutMode`/`layoutGrow`/고정폭 직독 (균등 vs 고정셀) | 규칙 일치 (행 값 복붙 ❌) |
| Canvas·게이지 위치 | 게이지/그래프 영역에 `align_probe.py` + bbox 중심·세로 figma 비교 (벡터 arc는 progress 스칼라 없음 → MCP path 끝점/bbox로 각 역산) | 중심 일치 |
| 레이아웃 위치·크기 | `align_probe.py` best(dx,dy) + 큰 suspect는 **bbox 크기** 직접 비교 | size 일치 & 시프트로 MAE 안 줆 → floor (dy가 fontSize 비례면 텍스트 메트릭=codegen, 위치 아님) |

**종료 게이트 (기계적·필수).** 수렴 선언 전 `ledger.json`(행별 `{verdict: pass|fixed|floor, evidence:
probe출력/crop 경로}`)을 쓰고 `scripts/ledger_gate.py ledger.json`이 **PASS**여야 종료한다 — 미실행 행이나
근거 없는 floor가 있으면 FAIL(종료 불가). 게이트 PASS 후 **반증 1패스**(독립 시각이 "한 건은 틀렸다 가정"하고
weight·색·글리프·분포·게이지를 탐색)까지 통과하면 종료. (서브에이전트 "수렴" 자가보고는 호출자가 ledger 근거로 재검증.)

## 보정 — 값 출처 & 픽셀 nudge 금지

확정된 오차만 Figma 선언값으로 교체한다. 보정값 출처 우선순위: **① Code Connect 매핑 구현값 재사용 →
② Figma MCP 직독 교체 — `get_design_context`로 layoutMode·itemSpacing·padding·gap·고정폭·layoutGrow·색
토큰, `get_metadata`로 인스턴스 bbox/box width(마스터≠인스턴스) → ③ 픽셀 엣지 역산 최후수단.** 큰 레버부터: **에셋 글리프(재export) > 레이아웃(선언값 교체) > AA floor.** 작은 letterSpacing·±2px는
전체 diff를 거의 안 움직이니 큰 suspect가 아이콘이면 위치보다 **글리프 재export**가 정답. 재export는
`figma-asset-download`로 올바른 노드 에셋을 받아 **플랫폼별 에셋 변환**(`references/<platform>.md`)을 거친다 — 손 전사 ❌.

- ⚠️ **align_probe dx/dy는 "어디가 틀렸나"만 — 정답값은 figma 선언값 직독** (숫자만 보고 ±N nudge 금지, 악화 실측).
- ⚠️ **부재·드리프트 섹션도 직독 복제 후에만 floor.** 인스턴스 선언값을 직독 교체(눈대중 스페이서 ❌)하고, **직독값이 코드와 이미 일치할 때만** 그 잔차가 floor(렌더 quirk: bbox≠콘텐츠폭·trailing·AA; 프로덕션도 같은 방식이면 안 베낌).

## 위임 인터페이스 (codegen Step 7c)

codegen이 호출할 때 넘기는 입력: `file_key`·`node_id`·crop 모드+인자·**빌드/실행 정보**(모듈·
variant·실행 타겟·platform) + (선택) **집중 영역 힌트**. design-qa가 빌드·진입·캡처를 자율 수행하므로 위임자는
앱을 미리 빌드/포그라운드 해둘 필요 없이 이 정보만 넘긴다.

반환: 코드 오차 확정 리스트(분류 포함) + `OVERLAY-REPORT.md` 경로. 위임 보정의 리포트에 담을 것: 페어 메타
(크기·resize_ratio) / 영역별 정합 표(영역·figma·real·판정·근거) / **잔여차를 코드 오차 vs 환경 아티팩트로 분리** /
(반복 시) 라운드별 요약 / blind-spot ledger 결과.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->
