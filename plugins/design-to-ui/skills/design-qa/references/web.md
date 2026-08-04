# design-qa — Web(Storybook) 캡처 계층 & 보정 어휘

SKILL.md의 중립 루프 중 **플랫폼 종속 부분(캡처·exact-crop)** 의 Web 구현과, 판정 rubric 처방의
**CSS/React 보정 어휘**를 담는다. (Android는 `references/android.md`, iOS는 `references/ios.md`.)

> 맥락: 이 계층은 web UI(React/Storybook) 마크업 ↔ Figma 정합 검증을 위해 design-qa의 **플랫폼 중립 비교
> 엔진(overlay·align_probe·glyph_probe·color_probe·edge_probe·enumerate_regions·ledger_gate)을 그대로
> 재사용**하고, 캡처 계층만 Playwright로 교체하며 만든 이식판이다. `overlay.py`·`align_probe.py`·
> `ledger_gate.py`·`edge_probe.py`·`enumerate_regions.py`는 무수정 재사용(좌표·dp 기반이라 플랫폼 무관),
> `glyph_probe.py`·`color_probe.py`에는 반전 컨텍스트용 `--mode`를 더했고, 웹용으로 `trim.py`·`run.mjs`·
> `capture_story.mjs`·`lib.mjs`를 추가했다. (`viewport.py`는 Android 전용 — 웹은 아래 0단계가 대응한다.)

## 실행 전제

- 대상이 **Storybook** 사용, `storybook-static` 빌드 존재(`npm run build-storybook`).
- **Playwright(chromium)** + **python3 + Pillow**. Figma MCP(`download_assets`, 토큰 불요 — `get_screenshot` 은 인라인 반환뿐이라 파일이 안 나온다).
- **대상 웹 프로젝트 루트에서 실행**한다(cwd 기준 경로 해소). Playwright는 대상 repo `node_modules`에서 동적 import.
- env override: `FIGMA_OVERLAY_STATIC`(storybook-static) / `OUT` / `FIGMA`(원본 캐시) / `PLAYWRIGHT` / `THEME_GLOBAL`.

## 0. 뷰포트 CSS px 정규화 (SKILL 워크플로우 0단계 — 캡처보다 먼저)

**Figma 프레임의 dp = 웹의 CSS px 다.** Playwright `viewport` 를 프레임 폭에 맞춘다. 웹은 네이티브보다 쉽다 —
`viewport` 와 `deviceScaleFactor` 를 **임의로** 지정할 수 있으므로 사다리 ②가 항상 성립하고, 중단(③)은
사실상 없다.

```js
const page = await browser.newPage({
  viewport: { width: 375, height: 812 },   // Figma 프레임 dp = CSS px
  deviceScaleFactor: 3,                    // figma export 와 픽셀 1:1 (375×3 = 1125px)
})
```

node-map 의 `width` 가 이미 그 역할을 한다 — **프레임 폭과 같은 값인지 확인**하고, 다르면 프레임 쪽에 맞춘다.
`width` 를 임의로 두면 미디어 쿼리·flex wrap·줄바꿈이 다르게 계산되어 오버레이가 성립하지 않는다(#181 과
같은 원인, 다른 표면). `overlay.py --figma-dp 375x812 --real-dp 375x812` 로 게이트를 켠다.

dp 외에 같이 고정할 것: 웹폰트 로딩(`document.fonts.ready` — 이미 캡처 계층이 대기한다), 테마
(`THEME_GLOBAL`, 프레임에 맞춰 전환·한쪽 고정 금지), 애니메이션(`prefers-reduced-motion` 또는 CSS 정지),
목 데이터.

> **미검증:** 위 처방은 #181(Android 실측)의 원리를 Web 표면으로 옮긴 것이고, `viewport` 불일치가 실제로
> 유령 오차를 만드는지 Storybook 에서 재현하지는 않았다.

## 1. 캡처 (SKILL 워크플로우 1단계)

`capture_story.mjs`가 Storybook 스토리를 요소 스크린샷으로 캡처한다. adb/simctl 대신 Playwright:
- 스토리 iframe 로드 → **`document.fonts.ready` 대기**(웹폰트 스와핑으로 인한 글자폭 오판 방지) →
  지정 selector의 **요소 bbox 스크린샷**.

## 2. exact-crop (SKILL 워크플로우 2단계)

웹은 **요소 bbox 스크린샷이 이미 정확**해, 네이티브의 dumpsys/simctl 좌표 추측(≈15px 오프셋 artifact) 문제가
없다 → **exact-crop이 대부분 불필요**. 남는 흰 여백만 `trim.py`(플랫폼 중립 `crop.py auto`의 웹 경량판)로 트림한다.
```bash
python3 scripts/trim.py <in.png> <out.png>
```

## 3. 오케스트레이션 (run.mjs)

`run.mjs`가 node-map(스토리 → Figma 컴포넌트 프레임 매핑)을 읽어 캡처→trim→overlay→리포트를 돈다.
Figma 원본은 캐시(`FIGMA_OVERLAY_FIGMA`)에 보존·재사용해 비싼 `download_assets` 재조회를 피한다(시안 바뀐 entry만 갱신).
```bash
node scripts/run.mjs            # node-map 전체
node scripts/run.mjs --only <entryId>
```
node-map 예시:
```json
{
  "$meta": { "fileKey": "<figma file key>" },
  "entries": [
    { "id": "scope-tabs-active", "story": "<storybook story id>", "selector": ".target-element",
      "theme": "light", "width": 375, "figmaNode": "2172:8857", "textParity": "fixed" }
  ]
}
```
- **figmaNode는 '컴포넌트 프레임' 노드**여야 한다(하위요소 아님).
- **textParity**: `fixed`(라벨·헤더·버튼 — 글자폭/굵기까지 대조) / `variable`(날짜·유저명·본문 등 가변 — glyph 제외).
- **id는 파일명 안전문자만**(영숫자·`.`·`_`·`-`; `/`·`..` 거부 — 경로 탈출 방지).

## 4. 반전 컨텍스트 — `color_probe`/`glyph_probe` `--mode`

흰 글자 / 컬러 배경(예: 그라데이션 토스트)은 기존 probe의 "밝은 배경 + 어두운 글자" 가정이 안 맞는다.
`--mode dark|light`를 더해 반전 컨텍스트의 의미색·글자폭/굵기를 측정한다(기존 동작은 그대로 보존).
```bash
python3 scripts/color_probe.py <real> --regions "n:L,T,R,B=#hex" --mode light   # 밝은 배경 위 어두운 글자
python3 scripts/glyph_probe.py --regions "n:L,T,R,B" --mode light
```

## 5. CSS/React 보정 어휘 (판정 rubric의 Web 처방)

SKILL은 *원칙*만 기술한다. 그 Web(CSS/React) 실제 처방:

### 세로 드리프트 — line-height / padding
크기 비례 세로 밀림은 `line-height`·수직 `padding`을 **Figma 선언값으로 직독 교체**한다(±N 픽셀 nudge 금지).
Figma line-height(px)를 그대로 `line-height`(px)로. flex 수직 정렬은 `align-items`.

### faux-bold — 글자 폭 어긋남
`font-weight: 700/500`이 실제 weight 폰트 없이 합성(faux)되면 advance가 어긋난다. 해당 weight의 실제
웹폰트를 `@font-face`로 등록해 합성 볼드를 피한다. (glyph_probe의 폭/coverage로 검출.)

### letterSpacing
Figma tracking을 `letter-spacing`으로 직독 교체(px 그대로 또는 em 환산). <1px라 metric 기여는 미미 — 큰 레버 아님.

### 위치/크기 — padding vs margin, box-sizing
공간 reserve가 필요하면 `padding`, 순수 시각 이동은 `margin`/`transform`. `box-sizing: border-box` 전제를 확인한다.

### 반전색 텍스트
그라데이션/컬러 배경 위 흰 글자는 `--mode light`로 측정하고, 색은 하드코딩 대신 CSS 변수(디자인 토큰)로 교체한다.

> 위 처방을 마크업/컴포넌트 작성 시 미리 반영하면 design-qa 재보정을 줄인다.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->
