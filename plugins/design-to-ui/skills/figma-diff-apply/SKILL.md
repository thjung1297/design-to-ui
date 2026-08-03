---
name: figma-diff-apply
description: Figma 변경을 디자이너 검수용 design/* 브랜치에 incremental 적용. /figma-apply 커맨드에서 위임 호출. design-to-ui(7-Step 새 화면 스캐폴딩)와 달리 변경된 컴포넌트만 식별·수정합니다. figma URL 1개(figma-driven) / 2개(diff-driven) 두 모드 지원. 새 화면 변환은 이 스킬 대신 design-to-ui를 사용하세요.
license: Apache-2.0
metadata:
  author: NAVER
  version: "1.1"
  requires: [project-design-system, figma-asset-download]
  platform: android
---

# figma-diff-apply

Figma URL의 현재 디자인과 design/* 브랜치의 현 코드를 대조하여 **변경된 컴포넌트만** 최소 수정으로 반영합니다. 신규 화면 전체 변환이 아니라 iteration(N→N+1) 시점에 사용합니다.

`design-to-ui`의 7-Step 풀 파이프라인을 호출하지 않습니다. 그 파이프라인은 "없던 화면을 처음 만들 때"에 최적화되어 있어, iteration마다 돌리면 토큰이 낭비되고 의도치 않은 전체 리팩토링 위험이 있습니다.

## 동작 모드

전달된 figma URL 수에 따라 두 모드로 분기합니다. 둘 다 baseline 비교라는 점은 같지만, 비교 대상의 baseline이 무엇인지가 다릅니다:

| 모드 | 입력 | baseline | 적합한 흐름 |
|------|------|---------|-----------|
| **figma-driven** (default) | figma URL 1개 | 현재 코드 (git working tree) | 디자이너가 URL만 던지는 일반 흐름. 누적된 코드↔디자인 격차도 함께 검수됨 |
| **diff-driven** (옵션) | figma URL 2개 (현재 + 이전 시점) | 이전 figma 응답 | 디자이너가 변경 시점을 명시하는 흐름. 토큰 ~80% 절감, scope 깔끔 |

> v6.1 mock 실험에서 두 모드 모두 5/5 통과 + false signal 0건 입증. 트레이드오프는 위 표 참조.

## Prerequisites

- 호출 시점에 `design/*` 브랜치가 체크아웃되어 있을 것 (`/figma-apply` Section 2가 보장)
- Figma Desktop MCP 연결(`get_design_context` 사용 가능) 또는 `FIGMA_ACCESS_TOKEN` 중 하나
- 프로젝트에 `.claude/skills/project-design-system/SKILL.md`가 존재 (있으면 토큰 매핑에 사용)

## 서브에이전트 위임 규칙

`design_context`는 변환의 원본이므로 **메인 컨텍스트에서 직접 읽습니다.** 서브에이전트에 "요약"을 맡기면 정확한 수치·중첩 구조가 소실됩니다(design-to-ui와 동일 원칙).

반대로 figma-driven 모드의 Phase 2 Diff·QA는 **반드시 서브에이전트로 분리**합니다. 메인이 후보 파일 전체와 분석 추론을 함께 들고 있으면 (1) 토큰이 부풀고 (2) QA가 자기평가 편향에 빠지며 (3) 후속 Phase 3 Edit이 불필요한 영역까지 손대기 쉬워집니다. (diff-driven 모드는 unix `diff`가 Diff Agent를 대체하므로 적용되지 않음.)

| 작업 | 서브에이전트 위임 | 이유 |
|------|:-:|------|
| design_context 읽기 | 금지 | 변환 원본 — 직접 봐야 정확 |
| 후보 파일 Read | 금지(메인) / **필수(서브)** | 메인은 파일 본문을 받지 않음. Phase 2a가 자기 컨텍스트에서 Read |
| Phase 2a Diff 분석 | **필수(후보 파일당 1개, 병렬)** | 컨텍스트 분리 + 병렬화로 토큰·시간 절감 |
| Phase 2b QA 검증 | **필수(독립 세션 1개)** | 자기평가 편향 차단 — Diff Agent 컨텍스트 미상속 |
| Phase 2c 재시도 | **필수(Phase 2a를 1회 재spawn)** | 같은 컨텍스트 재사용 금지 |
| Phase 3 Edit 적용 | 금지 | 식별 결과를 메인이 직접 적용해야 일관 |

### 컨텍스트 격리 contract

각 서브에이전트가 받는 입력과 반환하는 출력을 엄격히 한정합니다.

| Agent | 입력(받음) | 출력(반환) | 받지 않음 |
|-------|----------|-----------|----------|
| Diff Agent (N개) | 담당 후보 파일 경로 1개 + Figma `design_context` 발췌 + `get_screenshot` 이미지 + `get_variable_defs` JSON | Added/Changed/Removed/Moved 테이블 (구체값 명시) | 다른 후보 파일, 다른 Diff Agent의 산출물, 메인의 의사결정 메모 |
| QA Agent | Diff Agent들의 출력(병합) + screenshot + 후보 파일 경로 목록 | 4개 Binary Criteria 결과 + (FAIL 시) 이슈 목록 | Diff Agent의 추론 과정·중간 노트, 메인 컨텍스트 |
| Diff Agent (재시도) | 위 입력 + QA의 이슈 목록 | 갱신된 Diff 테이블 | 1차 시도의 내부 추론 |

메인 컨텍스트는 각 단계의 **최종 출력만** 받습니다. 후보 파일 전문, 분석 추론, 시도 횟수별 중간 산출물은 메인에 흘러들어오지 않습니다.

---

## Phase 1: 데이터 수집

### 1-1. Figma 스펙 (MCP 우선)

```javascript
// 병렬 호출
get_design_context(nodeId)
get_metadata(nodeId)
get_screenshot(nodeId)
get_variable_defs(nodeId)
```

**diff-driven 모드일 때**: `get_design_context`를 두 시점(`curr_nodeId` / `prev_nodeId`) 모두 호출. 두 응답을 임시 파일로 저장해 Phase 2의 `diff` 입력으로 사용.

MCP 미연결 시: 사용자에게 Figma Desktop 앱 실행을 안내(플러그인 CLAUDE.md "Figma MCP 사전 확인" 절). REST fallback이 필요하면 `figma-asset-download/scripts/`의 헬퍼를 활용.

### 1-2. 현 코드 후보 식별

baseline 파일은 사용하지 않습니다(이번 버전 범위 외). 대신 현 코드를 직접 탐색:

- `Glob("**/res/layout/*.xml")` + `Glob("**/*Compose*.kt")` 등으로 화면 후보 수집
- Figma 프레임 이름·`data-name`을 키워드로 `Grep` → 파일 좁히기
- Code Connect 매핑이 있으면 `get_code_connect_map(nodeId)` 호출 결과 우선

매핑 실패한 프레임은 "신규 컴포넌트"로 별도 분류하여 Phase 2 출력에 표시.

---

## Phase 2: Diff 분석

### figma-driven 모드 (URL 1개) — Generator/Evaluator 분리

> 서브에이전트 격리 원칙은 위 "서브에이전트 위임 규칙 / 컨텍스트 격리 contract" 표를 따릅니다.

#### Phase 2a: Diff Agent (후보 파일당 1개, 병렬)

Phase 1-2가 식별한 후보 파일이 N개면 `Agent` 도구를 **단일 응답에서 N번 병렬 호출**합니다(서로 의존 없음).

각 Agent 프롬프트에 포함하는 입력(이외에는 전달 금지):
- 담당 후보 파일 절대 경로 1개 (Agent가 자기 컨텍스트에서 직접 Read)
- 해당 파일에 매핑된 Figma 노드의 `design_context` 텍스트(필요 부분만 발췌)
- `get_screenshot` 이미지
- `get_variable_defs` JSON
- 분류·구체값 규칙 (아래)

반환 형식:
- **Added** — Figma에는 있고 코드에 없음
- **Changed** — 양쪽에 있으나 속성 다름
- **Removed** — 코드에 있고 Figma에 없음
- **Moved** — 위치/계층만 변경

각 항목에 **구체값 필수**: dp, hex, 토큰 경로(예: `Color.NaverGreen500`, `MaterialTheme.typography.titleLarge`), 에셋 SHA. "레이아웃 변경" 같은 모호 기술 금지.

메인은 N개 Agent의 출력 테이블만 받아 병합합니다. 각 Agent의 추론 과정·읽은 파일 본문은 메인 컨텍스트로 들어오지 않습니다.

#### Phase 2b: QA Agent (독립 세션 1개)

Phase 2a 병합 결과를 입력으로 **독립 세션 Agent 1회 호출**합니다. Diff Agent의 컨텍스트는 상속되지 않습니다.

QA Agent 프롬프트에 포함하는 입력:
- Phase 2a 병합 산출물(diff 테이블)
- `get_screenshot` 이미지
- 후보 파일 경로 목록 (QA가 필요 시 직접 Read하여 검증)

반환 형식: 4개 Binary Criteria 결과 + (FAIL 시) 이슈 목록.

Binary Criteria 4개:

| 기준 | PASS 조건 |
|------|-----------|
| 매핑 커버리지 | Figma 프레임의 80%+ 매핑됨 |
| 이미지 정합성 | Changed/Added 항목이 screenshot과 일치 (샘플 3개) |
| 변경 구체성 | 모호 기술 없음(dp/hex/토큰 명시) |
| 신규 식별 | 매핑 불가 프레임이 명시적으로 분류됨 |

하나라도 FAIL이면 전체 FAIL.

#### Phase 2c: 재시도 1회

QA가 FAIL이면 Phase 2a를 **새로운 서브에이전트로 1회 재spawn**합니다(1차 시도의 컨텍스트 재사용 금지 — 같은 세션을 살리면 같은 누락을 반복하기 쉽습니다). 재spawn 시 Phase 2a 입력에 QA의 이슈 목록을 추가.

2차도 FAIL이면 **경고를 붙여 Phase 3 진행**(분석 도구는 생성 도구보다 수렴이 빠르다는 캘린더팀 원칙).

---

### diff-driven 모드 (URL 2개) — unix `diff` short-circuit

서브에이전트 분리 없이 메인 컨텍스트가 두 figma 응답 텍스트를 직접 비교합니다. v6.1 mock 실험에서 SKILL 부재(L1) 환경의 메인이 자율 도출한 흐름이며, 아래와 같은 단순한 입력만으로 5/5 mock에서 figma-driven Full과 동등한 정확도를 보였습니다:

> "다음은 figma N+1 응답이고 (`<curr_nodeId>` 캡처 결과), 이전 figma 응답은 (`<prev_nodeId>` 캡처 결과)입니다. 차이를 찾아서 baseline 코드에 적용해주세요."

세부 단계는 메인이 자유롭게 결정합니다. 권장 흐름:

1. 두 figma 응답 텍스트를 unix `diff`로 비교 → 변경된 라인만 추출
2. 변경 라인에서 의미 있는 키워드(토큰명·class·data-name·asset SHA) 추출 후 후보 코드 파일에 `Grep`
3. 매핑된 위치에 최소 변경 적용

이후 **Phase 2b QA cross-check + Phase 2c retry는 figma-driven과 동일하게 호출** — self-evaluation 위험은 두 모드 공통이므로 생략하지 않습니다 (v6.1 L2 트랙: QA를 빼면 통과율 5/5 → 2/5로 무너짐).

> 💡 **diff-driven의 핵심 가치**: figma-driven에서 가장 큰 토큰 비용을 차지하는 Phase 2a Diff Agent N개 병렬 spawn을 unix `diff`로 대체. 결정적 텍스트 비교라 false signal 누수가 없고, 토큰은 약 80% 절감.

---

## Phase 3: 최소 변경 적용

식별된 변경 컴포넌트에 한정해 메인 컨텍스트가 `Edit`로 적용합니다.

규칙:
- **변경 없는 부분 건드리지 않음** — Phase 2 테이블에 없는 파일·요소는 수정 금지
- **색상·치수는 토큰 매핑** — `project-design-system`이 있으면 토큰으로, 없으면 기존 코드의 컨벤션 유지(하드코딩 금지)
- **신규 정적 에셋(Type A)** → `figma-asset-download` 위임 (design-to-ui Step 5 규칙 재사용). diff-driven 모드에서도 새 `imgXxx` 상수가 발견되면 동일하게 위임.
- **동적 비주얼(Type B, Canvas/그래프)** → SVG 다운로드 후 `Read`로 파라미터(stroke-width, opacity, path) 확인. 추측 금지
- **기존 에셋(Type C)** → `res/drawable` 재사용. 파일명만 보고 매핑 금지, Type C 검증 절차(design-to-ui Step 4)를 따름

---

## Phase 4: 결과 요약

```markdown
## figma-diff-apply 결과

### 변경 요약
| # | 유형 | 컴포넌트 | 상세 | 파일 |
|---|------|----------|------|------|
| 1 | Changed | TopBar.title | 18sp → 20sp | components/TopBar.kt:34 |
| 2 | Added | NotificationIcon | 우측 24dp 추가 | components/TopBar.kt:48 |

### QA 검증
| 매핑 커버리지 | PASS |
| 이미지 정합성 | PASS |
| 변경 구체성 | PASS |
| 신규 식별 | PASS |

### 신규 컴포넌트(매핑 실패)
- (없음)
```

---

## 금지사항

- **`design-to-ui` 7-Step 풀 파이프라인 호출 금지** — 이 스킬의 존재 이유 자체가 그 회피
- **baseline 파일(`.claude/context/ui-spec/*.md`) 참조 금지** — 이번 버전 범위 외, 후속 PR(`project-ui-spec` 도입)에서 다룸
- **QA Agent FAIL을 경고 없이 통과 금지** (두 모드 공통)
- **`design_context`를 서브에이전트에 위임해 "요약" 받지 않음**
- **Phase 2 테이블에 없는 파일·요소를 "함께 정리" 명목으로 수정 금지**

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->
