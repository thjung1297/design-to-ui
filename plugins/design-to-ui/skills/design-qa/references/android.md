# design-qa — Android 캡처 계층 & 보정 어휘

SKILL.md의 중립 루프 중 **플랫폼 종속 부분(캡처·exact-crop)** 의 Android 구현과, 판정 rubric
텍스트 처방의 **Compose 보정 어휘**를 담는다. (iOS는 같은 형식의 `references/ios.md`.)

**글리프 재export 변환:** `figma-asset-download`로 받은 SVG를 **vd-tool로 VectorDrawable(`*.xml`)** 로 변환해 `res/drawable/`에 둔다(codegen Android 에셋 파이프라인과 동일, 손 전사 ❌).

## 실행 전제

- `adb devices`에 기기/에뮬레이터 연결. **인프라 0** — 빌드된 앱 + adb만 필요.
- Figma Desktop MCP 연결 (오버레이 기준 이미지 `get_screenshot`용 — 토큰 불요). 글리프 재export 시에만 `figma-asset-download` 토큰(`FIGMA_ACCESS_TOKEN`, 권한 `file_content:read`) 필요.
- `python3` + `Pillow`(PIL)

## 1. 캡처 (SKILL 워크플로우 1단계)

```bash
OUT="$HOME/Desktop/design-qa/{검수화면}"; mkdir -p "$OUT"   # 기본 산출물 위치 — SKILL "산출물 위치(outdir)"
python3 "${CLAUDE_SKILL_DIR}/scripts/capture.py" "$OUT/cap_full.png"
```
`adb exec-out screencap`으로 풀스크린 PNG를 받는다.

> ⚠️ 캡처 전 대상 화면을 **force-stop → start → 포그라운드 확인** 후 찍는다. `am start`가 전환 중 stale/다른 프레임을 합성해 엉뚱한 화면(실측: 지도 프레임)이 잡혀 diff가 급증할 수 있다.

## 2. exact-crop (SKILL 워크플로우 2단계)

대상 창의 실제 경계로 정확히 잘라야 한다(좌표 추측 금지 — SKILL "exact-crop 원칙"). `scripts/crop.py`:

```bash
# frame 모드 (일반 — 대상 창이 포그라운드). dumpsys window 의 frame=[L,T,R,B] 자동 추출.
python3 "${CLAUDE_SKILL_DIR}/scripts/crop.py" frame \
  "$OUT/cap_full.png" "$OUT/real.png" \
  --package <pkg> --activity <Activity>
```

- **frame 모드**가 일반 Android 경로다. `dumpsys window windows`에서 대상 창 frame 을 crop 박스로 쓴다 — 구 포맷 `frame=[L,T,R,B]`(한 줄)와 현행 포맷 `Window{…pkg/activity}:` 뒤 `frame=[L,T][R,B]`(멀티라인) 모두 지원. 원점이 (0,0)이면 임베디드 로컬좌표 의심 경고를 낸다.
- `frame`이 안 되는 경우(임베디드/멀티윈도 등 창이 로컬좌표만 줌)의 crop 모드 선택은 **플랫폼 중립** — SKILL 워크플로우 참조(`crop.py`의 `auto`/`box`/`anchor`/정합 게이트는 플랫폼 무관).

## 3. Compose 보정 어휘 (판정 rubric D/E의 Android 처방)

SKILL은 *원칙*("크기 비례 세로 드리프트 = 텍스트 메트릭" 등)만 기술한다. 그 Android(Compose) 실제 처방:

### 텍스트 메트릭 — 크기 비례 세로 드리프트

전 텍스트에 **전역** 적용한다(개별 nudge ❌):
```kotlin
PlatformTextStyle(includeFontPadding = false)
LineHeightStyle(alignment = Alignment.Center, trim = Trim.None)
```
(실측: 온도 110sp MAE 10.59→0.86; 미세먼지 카드 "좋음"46sp 6px 위로 → 전역 적용 후 픽셀 일치.)

### faux-bold — 볼드/미디엄 글자 *폭* 어긋남

가변폰트(`*_variable.ttf`)를 weight 축 없이 단일 `Font()`로 등록하면 `FontWeight(700/500)`이 합성(faux)
bold로 렌더돼 advance가 어긋난다. weight 인스턴스를 명시 등록:
```kotlin
@OptIn(ExperimentalTextApi::class)
Font(R.font.x, weight = FontWeight.Bold,
     variationSettings = FontVariation.Settings(FontVariation.weight(700)))
```
(실측: 26° 폭 real 168 vs figma 174 → 등록 후 174 정확, pct_over_32 2.12→1.72%. 고치면 화면의 모든 볼드 텍스트가 동반 정합.)

### letterSpacing — 가로 글자 간격 차

figma tracking 값으로 직독 교체. `-0.5%` = `size × -0.005`(em). 단 <1px 효과라 metric 기여는 미미 — 큰 레버 아님.

### 위치/스케일 — padding vs offset

`Modifier.padding(start=N)`은 공간을 reserve해서 자식이 부모 폭을 넘기면 **압축**된다(실측: `padding(start=368)
.size(360)`이 부모 `Box(width=650)`를 넘겨 Image가 282로 압축). `offset`은 시각 이동이라 size를 유지한다
→ 위치 이동엔 offset, 또는 부모 Box 밖 overlay로. (offset의 좌표 기준 = 컨테이너 원점. figma frame
left를 raw로 쓰면 컨테이너 오프셋만큼 어긋남 — 실측 +78px.)

### 행 분포 (spread)

같은 5열이라도 figma에서 `layoutMode`/`primaryAxisAlignItems`/`layoutGrow`가 행마다 다를 수 있다 —
고정셀 `SpaceBetween`(`width(N)`) vs 균등 분할(`weight(1f)`)을 **행별로** 직독해 맞춘다. 한 행 값을 평행 행에 복붙 금지(실측: 부채꼴 벌어짐).

### per-text 의미색

매핑된 컴포넌트가 다른 브랜치(예: `origin/develop`)에 살아 있으면 그 구현의 `color =` 지정을 `git show`로
직독해 per-text 대조한다(실측: 주간 날짜·최저온도가 figma `alpha.2` 회색인데 코드는 검정 — develop 구현을 읽고 정정).

> 위 처방은 변환 시점(codegen)에 미리 박아두면 design-qa에서 재보정할 일이 줄어든다 — codegen의 Android 텍스트 정합 기본값과 동일 어휘다.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->
