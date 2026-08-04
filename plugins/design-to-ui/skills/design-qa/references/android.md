# design-qa — Android 캡처 계층 & 보정 어휘

SKILL.md의 중립 루프 중 **플랫폼 종속 부분(캡처·exact-crop)** 의 Android 구현과, 판정 rubric
텍스트 처방의 **Compose 보정 어휘**를 담는다. (iOS는 같은 형식의 `references/ios.md`.)

**글리프 재export 변환:** `figma-asset-download`로 받은 SVG를 **vd-tool로 VectorDrawable(`*.xml`)** 로 변환해 `res/drawable/`에 둔다(codegen Android 에셋 파이프라인과 동일, 손 전사 ❌).

## 실행 전제

- `adb devices`에 기기/에뮬레이터 연결. **인프라 0** — 빌드된 앱 + adb만 필요.
- Figma MCP 연결 (오버레이 기준 이미지는 `download_assets(defaultScale=k)` 로 받아 `export.url` 을 내려받는다 — 토큰 불요. `get_screenshot` 은 인라인 반환뿐이라 파일이 안 나온다). 글리프 재export 시에만 `figma-asset-download` 토큰(`FIGMA_ACCESS_TOKEN`, 권한 `file_content:read`) 필요.
- `python3` + `Pillow`(PIL)
- 시스템 바를 숨기는 앱은 새 기기에서 **"Viewing full screen" 안내 다이얼로그**가 1회 뜨는데, 이게 화면 위쪽을 덮고 나머지를 어둡게 만들어 오버레이를 통째로 망친다(실측 `mean_diff` 5.61 → 90.79, 보정 전후가 구별 불가). `viewport.py apply --freeze` 가 끄고 `reset` 이 직전값으로 되돌린다 — 직접 캡처할 때만 `adb shell settings put secure immersive_mode_confirmations confirmed`.

## 0. 뷰포트 dp 정규화 (SKILL 워크플로우 0단계 — 캡처보다 먼저)

**기기 dp 를 Figma 프레임 dp 에 맞춘 뒤에 캡처한다.** 안 맞추면 정합 게이트가 초록불을 주면서 유령 오차가
잡힌다(SKILL 0단계 실측표). `scripts/viewport.py` 가 3단 사다리를 수행한다.

```bash
FRAME_DP="360x780"                                   # Figma absoluteBoundingBox (get_metadata)

python3 "${CLAUDE_SKILL_DIR}/scripts/viewport.py" plan  "$FRAME_DP"            # 명령만 확인 (기기 불필요)
python3 "${CLAUDE_SKILL_DIR}/scripts/viewport.py" apply "$FRAME_DP" --freeze   # ①→② 사다리 + 검증 + 변수 고정
python3 "${CLAUDE_SKILL_DIR}/scripts/viewport.py" verify "$FRAME_DP"           # dp 대조 (overlay 에 넘길 값도 출력)
# … 캡처·오버레이·보정 루프 …
python3 "${CLAUDE_SKILL_DIR}/scripts/viewport.py" reset                        # 원복 (필수, 실패로 끝나도)
```

`apply` 가 하는 일 = `wm size` 와 `wm density` 를 **함께** 설정하는 것:

```bash
adb shell wm size 1080x2340     # (W×k) x (H×k),  k=3
adb shell wm density 480        # 160 × k        → 정확히 360×780dp @3배
```

- **`wm size` 를 함께 바꾸는 것이 핵심이다.** 물리 해상도(px)를 유지한 채 density 만 맞추려 하면 정수가
  안 떨어지고(375dp → 460.8), 그게 "이 기기로는 맞출 수 없다"는 **오판의 지점**이다. 물리 해상도보다 큰
  `wm size` 도 동작하므로(실측 1125 > 1080 에서 `screencap` 이 오버라이드 크기 그대로) 저해상도 기기에서도
  프레임 dp 를 @3x 로 맞출 수 있다. 배율 계산은 `viewport.py plan` 이 한다.
- ⚠️ **`wm size` 출력을 믿고 바로 캡처하면 안 된다 — 프레임버퍼 리사이즈는 비동기다.** 명령은 0.15s 에
  `Override size:` 를 보고하는데 `screencap` 이 실제로 그 크기가 되는 건 **~1.0s 뒤**다. 그 사이 캡처는
  이전 크기 이미지이고, 크기가 예전 값으로 일관되므로 **dp 게이트도 통과한다** — 조용히 틀린다.
  `viewport.py` 의 `apply`/`verify`/`reset` 은 실제 `screencap` 크기로 확인·대기해 이 함정을 넘어간다.
  직접 `wm size` 를 쓸 때는 캡처 크기를 반드시 검산할 것.
- **`--freeze` 가 같이 고정하는 dp 외 변수** (안 하면 줄바꿈·합성 프레임이 흔들린다):
  ```bash
  adb shell settings put system font_scale 1.0                 # 접근성 폰트 배율
  adb shell settings put global window_animation_scale 0
  adb shell settings put global transition_animation_scale 0   # 전환 중 프레임 합성 방지
  ```
  테마는 프레임에 맞춰 전환한다 — `adb shell cmd uimode night yes|no`. **한쪽으로 고정하지 말 것**: 다크/
  라이트 프레임이 둘 다 있으면 한쪽 고정은 나머지 절반을 미검증으로 남기는 것이다(프레임마다 두 번 돌린다).
  목/데모 데이터도 고정한다 — 문자열 길이가 바뀌면 줄바꿈과 오차 위치가 전부 바뀐다.
- ⚠️ **접히는 기기(resizable/foldable AVD)**: `wm` 오버라이드는 display-mode 전환을 견디지만 **`reset` 은
  그때의 구성에만 걸린다** — CLOSED 에서 `reset` 하고 OPENED 로 돌아가니 오버라이드가 다시 보였다.
  **적용한 구성에서 원복하고**, 구성을 바꿨으면 `verify` 를 한 번 더 돌린다(싸고 확실하다).
- 사다리 ③(adb 불가·OEM 이 `wm` 오버라이드를 막는 기기)이면 **중단하고 사용자에게 알린다.** `viewport.py`
  가 적용 후 검증에 실패하면 비정상 종료한다 — crop/배율로 흡수하려 하지 말 것.

## 1. 캡처 (SKILL 워크플로우 1단계)

```bash
OUT="$HOME/Desktop/design-qa/{검수화면}"; mkdir -p "$OUT"   # 기본 산출물 위치 — SKILL "산출물 위치(outdir)"
adb shell am force-stop <pkg>
adb shell am start -W -n <pkg>/.MainActivity          # monkey -c LAUNCHER 는 쓰지 말 것 (아래 ⚠️)
python3 "${CLAUDE_SKILL_DIR}/scripts/capture.py" "$OUT/cap_full.png" --expect-package <pkg>
```
`adb exec-out screencap`으로 풀스크린 PNG를 받는다. **`--expect-package` 를 항상 넘긴다.**

> ⚠️ 단색 검사는 검정 화면만 잡고 **그럴듯한 다른 화면**은 통과시킨다 — 실측: `monkey -c LAUNCHER` 가
> 조용히 실패해 **런처 홈**이 찍혔는데 dp·extent·resize 게이트가 전부 ok 인 채 `mean_diff 57.21` 만 남았다.
> 그래서 런치는 실패를 보고하는 `am start -W -n`, 캡처는 `--expect-package` 로 `mCurrentFocus` 를 검증한다.

> ⚠️ 캡처 전 대상 화면을 **force-stop → start → 포그라운드 확인** 후 찍는다. `am start`가 전환 중 stale/다른 프레임을 합성해 엉뚱한 화면(실측: 지도 프레임)이 잡혀 diff가 급증할 수 있다.
>
> ⚠️ 0단계에서 `wm size`/`wm density` 를 바꿨다면 **앱을 재시작한 뒤** 찍는다 — 살아 있는 액티비티가 이전
> 설정으로 이미 측정·배치돼 있을 수 있다. force-stop → start 가 그 역할을 겸한다.

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

### 엣지·full-bleed 구분선 — `edge_probe` 가 지목하는 처방

`edge_probe` 가 `Δstart +48 / Δend -47`(좌우가 안쪽으로 대칭) 을 찍으면 선이 **수평 패딩 안쪽**에 들어간
것이다. Figma 가이드의 구분선은 보통 프레임 폭을 꽉 채우는데(full-bleed), 부모 `Column`/`Card` 에 걸린
`Modifier.padding(horizontal = 16.dp)` 을 선까지 상속받으면 좌우 16dp 씩 짧아진다.

```kotlin
// ❌ 부모 패딩을 선까지 상속 — 좌우 16dp 짧아진다
Column(Modifier.padding(horizontal = 16.dp)) {
    Text(…)
    HorizontalDivider()                       // 328dp (360dp 프레임에서 32dp 부족)
}

// ✅ 콘텐츠에만 패딩, 선은 full-bleed
Column {
    Text(Modifier.padding(horizontal = 16.dp), …)
    HorizontalDivider()                       // 360dp
}
// 부모 패딩을 유지해야 하면 선만 되돌린다
HorizontalDivider(Modifier.padding(horizontal = (-16).dp))   // 또는 layout/offset 으로 상쇄
```

두께·색도 함께 직독한다 — `HorizontalDivider(thickness = 1.dp, color = …)`. 두께 기본값이 Figma 와 다르면
`edge_probe` 는 통과하고(시작·끝 좌표는 같으므로) 눈에만 남는다.

### 에셋 크기 — `--size-check` 가 지목하는 처방

`glyph_id_probe --size-check` 가 `Δ -2.00dp` 를 찍으면 아이콘이 Figma 선언보다 작게 그려진 것이다. 흔한 원인:

```kotlin
Icon(…, modifier = Modifier.size(24.dp))   // ← Figma 인스턴스 bbox 를 직독해 교체 (get_metadata)
```
- `Modifier.size()` 미지정 → 컴포넌트 기본값(Material `Icon` 은 24dp)이 먹는다.
- VectorDrawable 의 `android:width/height` 가 Figma 노드보다 작음 — 재export 시 뷰포트째 확인.
- 부모 제약에 눌림 — `Modifier.padding(start=N)` 은 공간을 reserve해서 자식을 **압축**한다(아래 "위치/스케일").
- ⚠️ 마스터≠인스턴스 bbox: 기대값은 **인스턴스** `absoluteBoundingBox` 다(SKILL 보정 값 출처 ②).

### per-text 의미색

매핑된 컴포넌트가 다른 브랜치(예: `origin/develop`)에 살아 있으면 그 구현의 `color =` 지정을 `git show`로
직독해 per-text 대조한다(실측: 주간 날짜·최저온도가 figma `alpha.2` 회색인데 코드는 검정 — develop 구현을 읽고 정정).

> 위 처방은 변환 시점(codegen)에 미리 박아두면 design-qa에서 재보정할 일이 줄어든다 — codegen의 Android 텍스트 정합 기본값과 동일 어휘다.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->
